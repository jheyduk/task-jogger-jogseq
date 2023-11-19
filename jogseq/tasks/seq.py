import readline  # isort:skip # noqa # enable arrow key support in input()

import datetime
import signal
from getpass import getpass
from os import path

from jogger.tasks import Task

from ..utils.duration import DurationContext, SwitchingCostScale, format_duration
from ..utils.jira import Jira, JIRAError
from ..utils.logseq import Block, Journal, Page


class Return(Exception):
    """
    Raised to trigger a return to the previous menu, or (if there is no
    previous menu) to exit the program.
    """
    
    def __init__(self, ttl=0):
        
        self.ttl = ttl
        
        super().__init__()
    
    def decrement_ttl(self):
        """
        Propagate (i.e. re-raise) the exception with a reduced TTL, unless the
        TTL has already expired.
        """
        
        if self.ttl:
            raise Return(ttl=self.ttl - 1)


def sigint_handler(signum, frame):
    
    # Raise Return to gracefully return to the previous menu
    raise Return()


signal.signal(signal.SIGINT, sigint_handler)


class Menu:
    """
    Encapsulates a menu of numerically-ordered options that can be displayed
    to the user to select from. The ``0`` option is reserved for a "return to
    previous menu" option, though the text used for the option can be
    configured with the ``return_option`` argument. The remaining options
    are configured with the ``other_options`` argument, which should be an
    iterable of either two- or three-tuples:
        
        (label, handler)
        OR
        (label, handler, args)
    
    Where the values are:
    
    - ``label``: The label to display for the option
    - ``handler``: The function to call when the option is selected
    - ``args``: A tuple of arguments to pass to the handler function
    """
    
    def __init__(self, return_option, other_options):
        
        super().__init__()
        
        self.return_option = return_option
        self.other_options = other_options
        
        handlers = {}
        for i, option in enumerate(other_options, start=1):
            handlers[i] = {
                'handler': option[1]
            }
            
            try:
                handlers[i]['args'] = option[2]
            except IndexError:  # args are optional
                pass
        
        self.handlers = handlers
    
    def get_display(self):
        """
        Return a string that can be printed to display the full menu.
        """
        
        options = []
        
        for i, option in enumerate(self.other_options, start=1):
            label = option[0]
            options.append(f'{i}. {label}')
        
        options.append(f'0. {self.return_option}')
        
        return '\n'.join(options)
    
    def prompt(self):
        """
        Prompt the user for a number corresponding to one of the menu options.
        
        For options other than ``0``, return the handler configuration for the
        selected option, as a dictionary containing:
        - ``handler``: The handler function
        - ``args``: The arguments to pass to the handler function. Only
            present if the three-tuple form of the option was used when
            instantiating the Menu.
        
        If ``0`` is selected, raise ``Return`` instead, to trigger a return to
        the previous menu. Also raise ``ValueError`` if the input is not a
        valid number, and ``KeyError`` if the number does not correspond
        to a valid menu option.
        
        :return: The handler dictionary for the selected option.
        """
        
        try:
            selection = input('\nChoose an option: ')
        except KeyboardInterrupt:
            selection = 0
        
        selection = int(selection)  # allow potential ValueError to propagate
        
        if selection == 0:  # always "return to the previous menu"
            raise Return()
        
        return self.handlers[selection]  # allow potential KeyError to propagate


class SeqTask(Task):
    
    DEFAULT_TARGET_DURATION = 7 * 60  # 7 hours
    DEFAULT_SWITCHING_COST = '0-0'  # min and max of 0 minutes (no switching cost)
    SWITCHING_COST_DURATION_RANGE = (5, 65)
    
    help = (
        'Begin the Logseq/Jira interactive integration program. This program '
        'provides several commands for synchronising Logseq and Jira.'
    )
    
    def handle(self, **options):
        
        self.verify_config()
        
        self.jira = self.configure_api()
        
        try:
            self.show_menu(
                '\nChoose one of the following commands to execute:',
                'Exit (or Ctrl+C)',
                ('Log work to Jira', self.handle_log_work),
                ('Summarise journals', self.handle_summarise_journals)
            )
        except (Return, EOFError):
            # The main menu was used to exit the program or Ctrl+D was pressed
            self.stdout.write('\nExiting...')
            raise SystemExit()
    
    def verify_config(self):
        
        # Verify `graph_path` setting
        try:
            graph_path = self.settings['graph_path']
        except KeyError:
            self.stderr.write('Invalid config: No graph path configured.')
            raise SystemExit(1)
        
        if not path.exists(graph_path):
            self.stderr.write('Invalid config: Graph path does not exist.')
            raise SystemExit(1)
        
        # Verify `switching_cost` setting
        try:
            self.get_switching_scale()
        except ValueError as e:
            self.stderr.write(str(e))
            raise SystemExit(1)
        
        # Verify remaining settings
        try:
            DurationContext.set_rounding_interval(self.settings.get('duration_interval', 1))
            self.get_target_duration()
            self.get_mark_done_when_logged()
            self.get_min_duration_for_summary()
        except ValueError as e:
            self.stderr.write(f'Invalid config: {e}')
            raise SystemExit(1)
    
    def configure_api(self):
        
        self.stdout.write('Connecting to Jira API...', style='label')
        
        # The URL and user are required settings
        try:
            jira_url = self.settings['jira_url']
            jira_user = self.settings['jira_user']
        except KeyError:
            self.stderr.write('Invalid config: Jira URL and/or user missing.')
            raise SystemExit(1)
        
        # The API token is optional. If not provided, prompt the user for it.
        jira_api_token = self.settings.get('jira_api_token', None)
        while not jira_api_token:
            jira_api_token = getpass('Jira API token: ')
        
        jira = Jira(jira_url, jira_user, jira_api_token)
        
        try:
            user_details = jira.api.myself()
        except JIRAError as e:
            if e.status_code == 401:
                self.stderr.write('Invalid Jira credentials.')
            else:
                self.stderr.write(f'Error connecting to Jira: {e}')
            
            raise SystemExit(1)
        
        user_name = user_details['displayName']
        user_email = user_details['emailAddress']
        
        self.stdout.write(f'Connected as: {user_name} ({user_email})', style='success')
        
        return jira
    
    def show_menu(self, intro, return_option, *other_options):
        """
        Recursively display a menu using the given arguments until a valid
        option is selected. Call the handler associated with the selected
        option and handle it raising a `Return` exception to return to the
        menu. Raise a `Return` exception outside a selected handler to return
        to the *previous* menu.
        
        :param intro: The message to display before the menu options.
        :param return_option: The label for the option to return to the
            previous menu. Always displayed as the last menu item, with
            an option number of 0.
        :param other_options: An iterable of other options to display in the
            menu. Each option is either a two- or three-tuple:
                    
                    (label, handler)
                    OR
                    (label, handler, args)
                
                Where the values are:
                
                - label: The label to display for the option
                - handler: The function to call when the option is selected
                - args: A tuple of arguments to pass to the handler function
        """
        
        menu = Menu(return_option, other_options)
        
        while True:
            self.stdout.write(intro, style='label')
            self.stdout.write(menu.get_display())
            
            selected_option = None
            while not selected_option:
                try:
                    selected_option = menu.prompt()
                except (ValueError, KeyError):
                    self.stdout.write('Invalid selection.', style='error')
            
            handler = selected_option['handler']
            args = selected_option.get('args', ())
            try:
                handler(*args)
            except Return as e:
                # The handler's process was interrupted in order to return
                # to a menu. Potentially re-raise the exception if it has a
                # non-zero TTL, indicating a return to a higher-level menu.
                e.decrement_ttl()
    
    def show_confirmation_prompt(self, prompt):
        """
        Display a yes/no confirmation prompt and raise ``Return`` if the user
        does not confirm the action. Any input other than "y" and "Y" is
        considered a "no".
        
        ``prompt`` does not need to end with a question mark, as one will be
        added automatically. Details on how to answer the prompt will also be
        included automatically (i.e. "[Y/n]").
        
        :param prompt: The prompt to display.
        """
        
        try:
            answer = input(f'{prompt} [Y/n]? ')
        except KeyboardInterrupt:
            answer = None  # no
        
        if answer.lower() != 'y':
            self.stdout.write('No action taken.')
            raise Return()
    
    def show_return_prompt(self, main_ttl=1):
        """
        Display a prompt asking the user whether to return to the main menu
        or the immediate parent menu. Raise ``Return`` either way, but use
        the given ``main_ttl`` if the user chooses to return to the main menu.
        
        :param main_ttl: The ``ttl`` value to pass to ``Return`` when
            returning to the main menu.
        """
        
        try:
            answer = input('Return to main menu [Y/n] (default=Y)? ')
        except KeyboardInterrupt:
            answer = ''  # yes
        
        if answer.lower() in ('y', ''):
            raise Return(ttl=main_ttl)
        
        raise Return()
    
    def get_date_from_offset(self, prompt, default=0):
        
        offset = input(f'{prompt} (default={default}): ')
        if not offset:
            offset = default
        
        try:
            offset = int(offset)
        except ValueError:
            self.stdout.write('Offset must be a positive integer.', style='error')
            return None
        
        if offset < 0:
            self.stdout.write('Offset must be a positive integer.', style='error')
            return None
        
        return datetime.date.today() - datetime.timedelta(days=offset)
    
    def parse_journal(self, journal=None, date=None, show_summary=False):
        """
        Parse a Logseq journal file and return a `Journal` object. Can either
        re-parse a file represented by an existing `Journal` object, or parse
        a new file given its date.
        
        Either way, upon successfully parsing the file, a brief summary of its
        contents is displayed. This can be disabled by passing `show_summary`
        as `False`.
        
        :param journal: Optional. An existing `Journal` object to re-parse.
        :param date: Optional. The date of a new journal file to parse.
        :param show_summary: Whether to show a summary of the journal's
            contents after parsing it.
        """
        
        if not journal and not date:
            raise TypeError('One of "journal" or "date" must be provided.')
        
        switching_scale = self.get_switching_scale()
        
        if not journal:
            journal = Journal(self.settings['graph_path'], date, switching_scale, self.jira)
        
        self.stdout.write(f'Parsing journal for: {journal.date}…', style='label')
        
        try:
            journal.parse()
        except FileNotFoundError:
            self.stdout.write('No journal found for date', style='error')
            return None
        
        if show_summary:
            journal.validate()
            self.show_journal_summary(journal)
        
        return journal
    
    def get_target_duration(self):
        """
        Return the configured target duration in seconds.
        """
        
        try:
            duration = int(self.settings.get('target_duration', self.DEFAULT_TARGET_DURATION))
        except ValueError:
            duration = 0
        
        if duration <= 0:
            raise ValueError('Target duration must be a positive number of minutes.')
        
        return duration * 60  # convert from minutes to seconds
    
    def get_switching_scale(self):
        """
        Return a ``SwitchingCostScale`` object for the calculation of estimated
        switching costs based on task durations.
        """
        
        cost_setting = self.settings.get('switching_cost', self.DEFAULT_SWITCHING_COST)
        
        return SwitchingCostScale(cost_setting, self.SWITCHING_COST_DURATION_RANGE)
    
    def get_mark_done_when_logged(self):
        """
        Return the configured `mark_done_when_logged` flag.
        """
        
        mark_done = self.settings.get('mark_done_when_logged', 'true').lower()
        
        if mark_done in ('true', '1'):
            return True
        elif mark_done in ('false', '0'):
            return False
        else:
            raise ValueError('Invalid value for "mark_done_when_logged" setting.')
    
    def get_min_duration_for_summary(self):
        """
        Return the configured minimum duration for summarised issues, in seconds.
        Issues with a total duration over the summary period less than this
        value will be omitted from the summary.
        """
        
        try:
            duration = int(self.settings.get('min_duration_for_summary', 0))
        except ValueError:
            duration = -1
        
        if duration < 0:
            raise ValueError(
                'Minimum duration for summary must be a number of minutes'
                ' greater than or equal to zero.'
            )
        
        return duration * 60  # convert from minutes to seconds
    
    def show_journal_summary(self, journal):
        """
        Display a summary of the given `Journal` object's contents, including
        any problems detected while parsing it.
        """
        
        show_summary = True
        show_problems = True
        
        if journal.is_fully_logged:
            # All worklog blocks in this journal have been logged to Jira.
            # Give a summary of totals, but don't report problems (no further
            # actions can be taken on the journal anyway)
            self.stdout.write('Journal is fully logged', style='success')
            show_problems = False
        elif not journal.tasks:
            # The journal is either empty or its tasks could not be extracted
            # for some reason. Don't show a summary (there will be nothing to
            # include anyway), but show any problems that may have prevented
            # processing the journal's tasks.
            self.stdout.write('Nothing to report', style='warning')
            show_summary = False
        else:
            num_tasks = self.styler.label(len(journal.tasks))
            num_unlogged = self.styler.label(len(journal.unlogged_worklogs))
            self.stdout.write(
                f'Found {num_unlogged} unlogged worklog entries'
                f' (out of {num_tasks} total tasks)'
            )
        
        if show_summary:
            switching_cost = journal.total_switching_cost
            switching_cost_str = self.styler.label(format_duration(switching_cost))
            switching_cost_suffix = ''
            if not journal.misc_block:
                switching_cost_suffix = self.styler.error(' (unloggable)')
            
            self.stdout.write(f'\nEstimated context switching cost: {switching_cost_str}{switching_cost_suffix}')
            
            unloggable_duration = journal.unloggable_duration
            if unloggable_duration:
                unloggable_duration_str = self.styler.label(format_duration(unloggable_duration))
                self.stdout.write(f'Time against non-worklog tasks: {unloggable_duration_str}')
            
            total_duration = journal.total_duration
            total_duration_str = self.styler.label(format_duration(total_duration))
            self.stdout.write(f'Total time: {total_duration_str}')
            
            # Calculate the "slack time" based on the target duration and the
            # total duration of all tasks
            target_duration = self.get_target_duration()
            slack_time = max(target_duration - total_duration, 0)
            if slack_time > 0:
                slack_time_str = self.styler.warning(format_duration(slack_time))
            else:
                slack_time_str = self.styler.label('None! You work too hard.')
            
            self.stdout.write(f'Slack time: {slack_time_str}')
        
        if show_problems and journal.problems:
            self.stdout.write('')  # blank line
            for msg in journal.problems:
                self.stdout.write(msg.get_log_message(self.styler))
    
    def show_worklog_summary(self, task):
        
        errors = task.validate(self.jira)
        error_types = [e.type for e in errors]
        
        issue_id = task.issue_id
        if 'issue_id' in error_types and 'keyword' not in error_types:
            issue_id = self.styler.error(issue_id)
        
        duration = task.get_total_duration()
        if not duration:
            duration = '???'
        else:
            duration = format_duration(duration)
        
        if 'duration' in error_types and 'keyword' not in error_types:
            duration = self.styler.error(duration)
        
        output = f'{issue_id}: {duration}'
        description = task.sanitised_content
        if description:
            output = f'{output}; {description}'
        
        if 'keyword' in error_types:
            output = self.styler.error(output)
        
        extra_lines = '\n'.join(task.get_all_extra_lines())
        if extra_lines:
            output = f'{output}\n{extra_lines}'
        
        self.stdout.write(output)
    
    def _check_journal_fully_logged(self, journal):
        
        if journal.is_fully_logged:
            self.stdout.write(
                '\nFully logged journals cannot be processed further',
                style='warning'
            )
            raise Return()
    
    #
    # Log work
    #
    
    def handle_log_work(self):
        
        self.stdout.write('\nChoose which day to log work for. Defaults to today.', style='label')
        self.stdout.write(
            'Enter an offset from the current day. '
            'E.g. 0 = today, 1 = yesterday, 2 = the day before, etc.'
        )
        
        journal = None
        while not journal:
            date = self.get_date_from_offset(prompt='\nOffset', default=0)  # default to "today"
            if not date:
                continue
            
            self.stdout.write('')  # blank line
            journal = self.parse_journal(date=date, show_summary=True)
        
        handler_args = (journal, )
        self.show_menu(
            '\nJournal options:',
            'Return to main menu',
            ('Show worklog summary', self.handle_log_work__show_worklog, handler_args),
            ('Submit worklog', self.handle_log_work__submit_worklog, handler_args),
            ('Mark all work as logged', self.handle_log_work__mark_logged, handler_args),
            ('Update journal', self.handle_log_work__update_journal, handler_args),
            ('Re-parse journal', self.handle_log_work__reparse_journal, handler_args)
        )
    
    def handle_log_work__show_worklog(self, journal):
        
        if not journal.worklogs:
            self.stdout.write('\nJournal contains no worklog entries to summarise', style='warning')
            return
        
        logged = journal.logged_worklogs
        unlogged = journal.unlogged_worklogs
        
        if logged:
            self.stdout.write('\nLogged work summary:\n', style='label')
            
            for task in logged:
                self.show_worklog_summary(task)
        
        if unlogged:
            self.stdout.write('\nUnlogged work summary:\n', style='label')
            
            for task in unlogged:
                self.show_worklog_summary(task)
    
    def handle_log_work__submit_worklog(self, journal):
        
        self._check_journal_fully_logged(journal)
        
        unlogged = journal.unlogged_worklogs
        
        if not unlogged:
            self.stdout.write('\nJournal contains no unlogged worklog entries to submit', style='warning')
            return
        
        problems = [e for task in unlogged for e in task.validate(self.jira)]
        for p in problems:
            self.stdout.write(p.get_log_message(self.styler))
        
        if problems:
            self.stdout.write(
                '\nThe above problems were found in unlogged worklog entries.'
                ' Please correct them before proceeding.',
                style='error'
            )
            return
        
        self.stdout.write(
            '\nIf you continue, the worklog entries in this journal will be'
            ' submitted to Jira. The journal file will then be updated to'
            ' reflect any processing performed by this program, flag those'
            ' blocks as logged, and note the details of the submission.'
        )
        
        self.show_confirmation_prompt('Are you sure you wish to continue')
        
        self.stdout.write(f'\nSubmitting {len(unlogged)} worklog entries...', style='label')
        
        set_done = self.get_mark_done_when_logged()
        
        successful = 0
        unsuccessful = 0
        for task in unlogged:
            description = task.sanitised_content
            extra_lines = '\n'.join(task.get_all_extra_lines())
            if extra_lines:
                description = f'{description}\n{extra_lines}'
            
            try:
                self.jira.api.add_worklog(
                    task.issue_id,
                    timeSpentSeconds=task.get_total_duration(),
                    comment=description
                )
            except Exception as e:
                self.stderr.write(
                    'The following error occurred attempting to submit a worklog'
                    f' entry to issue {task.issue_id}. You may need to manually'
                    ' log this entry.',
                    style='error'
                )
                self.stdout.write(f'The error was:\n{e}')
                unsuccessful += 1
            else:
                task.mark_as_logged(set_done=set_done)
                successful += 1
        
        self.stdout.write('')  # blank line
        
        if successful:
            self.stdout.write(f'Added {successful} worklog entries in Jira.', style='success')
        
        if unsuccessful:
            self.stdout.write(f'{unsuccessful} worklog entries failed. See above for details.', style='error')
        
        # Set the journal as fully logged without marking all worklogs as
        # logged - that will have been done individually above, if successful
        journal.set_fully_logged(update_worklogs=False)
        
        journal.write_back()
        
        self.stdout.write('\nJournal file updated.', style='success')
        
        self.show_return_prompt()
    
    def handle_log_work__mark_logged(self, journal):
        
        self._check_journal_fully_logged(journal)
        
        unlogged = journal.unlogged_worklogs
        
        if not unlogged:
            self.stdout.write('\nJournal contains no unlogged worklog entries to mark as logged', style='warning')
            return
        
        self.stdout.write(
            '\nIf you continue, all worklog entries in this journal not'
            ' currently marked as logged will be marked as such. These changes'
            ' will NOT be written back to the Logseq markdown file. Use the'
            ' "Update journal" option to persist them.'
        )
        
        self.show_confirmation_prompt('Are you sure you wish to continue')
        
        if journal.problems:
            self.stdout.write(
                '\nProblems were found parsing this journal. Continuing may'
                ' result in incorrect or incomplete entries being marked as logged.'
            )
            
            self.show_confirmation_prompt('Are you REALLY sure you wish to continue')
        
        num_unlogged = len(unlogged)
        
        journal.set_fully_logged(set_done=self.get_mark_done_when_logged())
        
        self.stdout.write(f'\nMarked {num_unlogged} worklog entries as logged.', style='success')
    
    def handle_log_work__update_journal(self, journal):
        
        self._check_journal_fully_logged(journal)
        
        if not journal.tasks:
            self.stdout.write('\nJournal contains no tasks to update', style='warning')
            return
        
        self.stdout.write(
            '\nIf you continue, the source Logseq file for this journal will'
            ' be updated to reflect any processing performed by this program'
            ' (e.g. converting time:: properties), and to note calculated'
            ' totals (e.g. total duration and estimated switching cost).'
        )
        
        self.show_confirmation_prompt('Are you sure you wish to continue')
        
        journal.write_back()
        
        self.stdout.write('\nJournal file updated.', style='success')
        
        self.show_return_prompt()
    
    def handle_log_work__reparse_journal(self, journal):
        
        self.stdout.write('')  # blank line
        self.parse_journal(journal=journal, show_summary=True)
    
    #
    # Summarise journals
    #
    
    def _build_worklog_digest(self, start_date, end_date):
        
        total_duration = 0
        total_count = 0
        skip_counts = {
            'misc': 0,
            'no_content': 0,
            'low_duration': 0
        }
        
        # Build up a map of Jira issue IDs to Blocks that summarise the work
        # done for those issues
        issue_blocks = {}
        
        next_date = start_date
        while next_date <= end_date:
            journal = self.parse_journal(date=next_date)
            next_date += datetime.timedelta(days=1)
            
            if not journal:
                continue
            
            for entry in journal.worklogs:
                total_count += 1
                
                entry_duration = entry.get_total_duration()
                total_duration += entry_duration
                
                if 'misc' in entry.properties:
                    skip_counts['misc'] += 1
                    continue
                elif not entry.description and not entry.get_all_extra_lines():
                    skip_counts['no_content'] += 1
                    continue
                
                # If this is the first time this Jira issue has been seen in
                # the given range, create a parent Block for it
                issue_id = entry.issue_id
                if issue_id not in issue_blocks:
                    issue_block = Block(content=f'- #### {issue_id}:')
                    issue_blocks[issue_id] = issue_block
                    
                    # Add a `duration` property to track the total duration
                    # of all worklogs added to the issue
                    issue_block.properties['duration'] = 0
                
                # Create a new Block for this entry, with summarised content,
                # nested under the issue ID block
                content = f'- *{journal.date:%a, %b %-d}*: {entry.sanitised_content}'
                block = Block(content=content, parent=issue_blocks[issue_id])
                block.continuation_lines = entry.continuation_lines
                block.children = entry.children
                block.parent.properties['duration'] += entry_duration
        
        self.stdout.write('\nPreparing worklog digest…')
        
        page = Page(self.settings['graph_path'], 'Worklog Digest')
        
        date_format = '%a, %b %-d, %Y'
        page.properties = {
            'from-date': start_date.strftime(date_format),
            'to-date': end_date.strftime(date_format),
            'total-worklogs': total_count,
            'total-duration': format_duration(total_duration)
        }
        
        # Don't add skip counts as properties, as they don't need to be written
        # to the markdown file, but annotate them onto the Page object for use
        # by the caller
        page.skip_counts = skip_counts
        
        # Add issue blocks as children of the page, in order of issue ID
        min_duration = self.get_min_duration_for_summary()
        for issue_id in sorted(issue_blocks):
            block = issue_blocks[issue_id]
            
            issue_duration = block.properties['duration']
            
            # If the total duration logged for the issue across the summary
            # period doesn't meet the configured threshold, omit the issue
            if min_duration and issue_duration < min_duration:
                skip_counts['low_duration'] += len(block.children)
                continue
            
            # Format the `duration` property for display
            block.properties['duration'] = format_duration(issue_duration)
            
            # Fetch the issue title from Jira and append to the block's
            # content line
            issue_title = self.jira.get_issue_title(issue_id) or ''
            block.content = f'{block.content} {issue_title}'
            
            page.children.append(block)
        
        return page
    
    def handle_summarise_journals(self):
        
        self.stdout.write(
            '\nChoose a date range to summarise.'
            ' Defaults to the last 7 days, including today.',
            style='label'
        )
        self.stdout.write(
            'Enter two offsets from the current day. '
            'E.g. 0 = today, 1 = yesterday, 2 = the day before, etc.'
        )
        
        end_date = None
        while not end_date:
            end_date = self.get_date_from_offset(prompt='End offset', default=0)
        
        start_date = None
        while not start_date:
            start_date = self.get_date_from_offset(prompt='Start offset', default=6)
        
        end_date_str = self.styler.label(end_date.strftime('%y-%m-%d'))
        start_date_str = self.styler.label(start_date.strftime('%y-%m-%d'))
        self.stdout.write(f'\nSummarising journals between {start_date_str} and {end_date_str}…')
        
        digest_page = self._build_worklog_digest(start_date, end_date)
        
        properties = digest_page.properties
        total_count_str = self.styler.label(properties['total-worklogs'])
        total_duration_str = self.styler.label(properties['total-duration'])
        self.stdout.write(f'\nFound {total_count_str} worklog entries totalling {total_duration_str}')
        
        skip_counts = digest_page.skip_counts
        misc_count_str = self.styler.label(skip_counts['misc'])
        no_content_count_str = self.styler.label(skip_counts['no_content'])
        low_duration_count_str = self.styler.label(skip_counts['low_duration'])
        self.stdout.write(f'Skipped {misc_count_str} "miscellaneous" entries')
        self.stdout.write(f'Skipped {no_content_count_str} entries without content')
        self.stdout.write(f'Skipped {low_duration_count_str} entries for low-duration issues')
        
        leftovers = properties['total-worklogs'] - sum(skip_counts.values())
        if not leftovers:
            self.stdout.write('\nNothing left to summarise', style='warning')
            return
        
        leftovers_str = self.styler.label(leftovers)
        issue_count_str = self.styler.label(len(digest_page.children))
        self.stdout.write(f'\nSummarised remaining {leftovers_str} entries for {issue_count_str} issues')
        
        digest_page.write_back(escape_lines=True)
        
        self.stdout.write(
            f'\nSummary written to the {digest_page.title} page in your Logseq graph',
            style='success'
        )
