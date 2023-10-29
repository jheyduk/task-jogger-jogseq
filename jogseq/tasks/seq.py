import datetime
import math
from getpass import getpass
from os import path

from jogger.tasks import Task

from ..utils.blocks import DurationContext, Journal, format_duration
from ..utils.jira import Jira, JIRAError


def set_duration_interval(interval):
    
    try:
        interval = int(interval)
    except ValueError:
        pass
    
    if interval == 1:
        DurationContext.rounding_interval = DurationContext.ONE_MINUTE
    elif interval == 5:
        DurationContext.rounding_interval = DurationContext.FIVE_MINUTES
    else:
        raise ValueError('Duration interval must be either 1 or 5.')


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


class Menu(dict):
    """
    Dictionary subclass that is instantiated, not with key-value pairs, but
    with an iterable of menu options. Each option is either a two- or three-
    tuple:
        
        (label, handler)
        OR
        (label, handler, args)
    
    Where the values are:
    
    - label: The label to display for the option
    - handler: The function to call when the option is selected
    - args: A tuple of arguments to pass to the handler function
    
    This `options` iterable is used to populate the dictionary, with the
    keys being integers starting from 1, and the values being dictionaries
    themselves, with the following keys:
    
    - handler: The handler function
    - args: The arguments to pass to the handler function. Only present if the
        three-tuple form of the option was used.
    
    The 0 key is reserved for the "return to previous menu" option. Accessing
    this key will raise a `Return` exception.
    """
    
    def __init__(self, options):
        
        super().__init__()
        
        for i, option in enumerate(options, start=1):
            self[i] = {
                'handler': option[1]
            }
            
            try:
                self[i]['args'] = option[2]
            except IndexError:  # args are optional
                pass
    
    def __getitem__(self, key):
        
        # The 0 option is always "return to the previous menu"
        if key == 0:
            raise Return()
        
        return super().__getitem__(key)


class SwitchingCostScale:
    """
    Helper object for containing scaling switching cost details and calculating
    estimated switching costs for given task durations.
    """
    
    def __init__(self, cost_range, duration_range):
        
        # Convert duration min/max given in minutes to seconds
        min_duration, max_duration = duration_range
        self.min_duration = min_duration * 60
        self.max_duration = max_duration * 60
        
        # Convert switching cost min/max given in minutes to seconds
        min_cost, max_cost = self._extract_costs(cost_range)
        self.min_cost = min_cost * 60
        self.max_cost = max_cost * 60
        
        if min_cost == max_cost:
            # There is no range of switching costs, only a single value. No
            # sliding scale needs to be used.
            self.cost_scale = None
            self.duration_step = None
        else:
            # Store a list of the full range of switching costs, in seconds
            self.cost_scale = [i * 60 for i in range(min_cost, max_cost + 1)]
            
            # Calculate the "duration step" - the number of seconds of a duration
            # between each switching cost in the above scale. E.g. there may be
            # 5 minutes (300 seconds) worth of duration between each switching cost
            # (10 minutes of duration may incur a 2 minute switching cost, and 15
            # minutes of duration may incur a 3 minute switching cost, etc).
            cost_diff = max_cost - min_cost
            duration_diff = max_duration - min_duration
            self.duration_step = math.ceil(duration_diff / cost_diff) * 60
    
    def _extract_costs(self, cost_range):
        
        invalid_msg = (
            'Invalid config: Switching cost must be a range of minutes,'
            ' e.g. 1-15, 5-30, etc.'
        )
        
        try:
            min_cost, max_cost = cost_range.split('-')
            min_cost, max_cost = int(min_cost), int(max_cost)
        except ValueError:
            raise ValueError(invalid_msg)
        
        if min_cost < 0 or min_cost > max_cost:
            raise ValueError(invalid_msg)
        
        # Find the maximum span of a switching cost range that can be
        # configured for the given duration range. The span of switching
        # costs must be under half that of the duration. E.g. a duration
        # range of 0-60 minutes supports a maximum switching cost span of
        # 30 minutes. That could mean a range of 0-30 minutes, 15-45
        # minutes, etc. Shorter spans are valid as well, this only
        # gives the maximum possible.
        max_range = int((self.max_duration - self.min_duration) / 60 / 2)
        
        if max_cost - min_cost > max_range:
            raise ValueError(
                'Invalid config: Switching cost must be a range spanning no'
                f' more than {max_range} minutes.'
            )
        
        return min_cost, max_cost
    
    def for_duration(self, duration):
        """
        Return the switching cost for the given duration, in seconds.
        """
        
        if not self.cost_scale:
            # There is only a single switching cost, so use that
            return self.min_cost
        
        # Calculate the appropriate switching cost based on a sliding scale
        # relative to the given duration. If the duration exceeds the bounds
        # of the scale, use the min/max switching cost as appropriate.
        if duration <= self.min_duration:
            return self.min_cost
        elif duration >= self.max_duration:
            return self.max_cost
        else:
            index = duration // self.duration_step
            return self.cost_scale[index]


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
                ('Log work to Jira', self.handle_log_work)
            )
        except Return:
            # The main menu was used to exit the program
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
        
        # Verify `duration_interval` setting
        try:
            set_duration_interval(self.settings.get('duration_interval', 1))
        except ValueError as e:
            self.stderr.write(f'Invalid config: {e}')
            raise SystemExit(1)
        
        # Verify `target_duration` setting
        try:
            self.get_target_duration()
        except ValueError as e:
            self.stderr.write(f'Invalid config: {e}')
            raise SystemExit(1)
        
        # Verify `switching_cost` setting
        try:
            self.get_switching_scale()
        except ValueError as e:
            self.stderr.write(str(e))
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
        
        menu = Menu(other_options)
        
        while True:
            self.stdout.write(intro, style='label')
            
            for i, option in enumerate(other_options, start=1):
                label = option[0]
                self.stdout.write(f'{i}. {label}')
            
            self.stdout.write(f'0. {return_option}')
            
            selected_option = None
            while not selected_option:
                try:
                    selection = input('\nChoose an option: ')
                except KeyboardInterrupt:
                    selection = 0
                
                try:
                    selected_option = menu[int(selection)]
                except (ValueError, IndexError):
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
    
    def parse_journal(self, journal=None, date=None, show_summary=True):
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
        
        self.stdout.write(f'\nParsing journal for: {journal.date}…', style='label')
        
        try:
            journal.parse()
        except FileNotFoundError:
            self.stdout.write('No journal found for date', style='error')
            return None
        
        if show_summary:
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
            
            for level, msg in journal.problems:
                if level == 'error':
                    styler = self.styler.error
                elif level == 'warning':
                    styler = self.styler.warning
                else:
                    styler = self.styler.label
                
                prefix = styler(f'[{level.upper()}]')
                self.stdout.write(f'{prefix} {msg}')
    
    def show_worklog_summary(self, task):
        
        errors = task.validate(self.jira)
        
        issue_id = task.issue_id
        if 'issue_id' in errors and 'keyword' not in errors:
            issue_id = self.styler.error(issue_id)
        
        duration = task.get_total_duration()
        if not duration:
            duration = '???'
        else:
            duration = format_duration(duration)
        
        if 'duration' in errors and 'keyword' not in errors:
            duration = self.styler.error(duration)
        
        output = f'{issue_id}: {duration}'
        description = task.sanitised_content
        if description:
            output = f'{output}; {description}'
        
        if 'keyword' in errors:
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
    # Menu option handlers
    #
    
    def handle_log_work(self):
        
        self.stdout.write('\nChoose which day to log work for. Defaults to today.', style='label')
        self.stdout.write(
            'Enter an offset from the current day. '
            'E.g. 0 = today, 1 = yesterday, 2 = the day before, etc.'
        )
        
        journal = None
        while not journal:
            offset = input('\nOffset (default=0): ')
            if not offset:
                offset = 0  # default to "today"
            
            try:
                offset = int(offset)
            except ValueError:
                self.stdout.write('Offset must be a positive integer.', style='error')
                continue
            
            if offset < 0:
                self.stdout.write('Offset must be a positive integer.', style='error')
                continue
            
            date = datetime.date.today() - datetime.timedelta(days=offset)
            
            journal = self.parse_journal(date=date)
        
        handler_args = (journal, )
        self.show_menu(
            '\nJournal options:',
            'Return to main menu',
            ('Show worklog summary', self.handle_log_work__show_worklog, handler_args),
            ('[unimplemented] Submit worklog', self.handle_log_work__submit_worklog, handler_args),
            ('Mark all work as logged', self.handle_log_work__mark_logged, handler_args),
            ('Update journal', self.handle_log_work__update_journal, handler_args),
            ('Re-parse journal', self.parse_journal, handler_args)
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
        
        self.stdout.write(
            '\nIf you continue, the worklog entries in this journal will be'
            ' submitted to Jira. The journal file will then be updated to'
            ' reflect any processing performed by this program, flag those'
            ' tasks as done, and note the details of the submission.'
        )
        
        self.show_confirmation_prompt('Are you sure you wish to continue')
        
        if journal.problems:
            self.stdout.write(
                '\nProblems were found parsing this journal. Continuing may'
                ' result in incorrect or incomplete worklog entries being'
                ' submitted to Jira. It may even result in data loss when'
                ' updating the journal file.'
            )
            
            self.show_confirmation_prompt('Are you REALLY sure you wish to continue')
        
        # TODO: Submit via API and update journal
        self.stdout.write('Not implemented.', style='error')
    
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
        
        journal.mark_all_logged()
        
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
        
        if journal.problems:
            self.stdout.write(
                '\nProblems were found parsing this journal. Continuing may'
                ' result in data loss when updating the journal file.'
            )
            
            self.show_confirmation_prompt('Are you REALLY sure you wish to continue')
        
        journal.write_back()
        
        self.stdout.write('\nJournal file updated.', style='success')
        input('Hit ENTER to return to the main menu...')
        raise Return(ttl=1)  # skip "log work" menu and return to main menu
