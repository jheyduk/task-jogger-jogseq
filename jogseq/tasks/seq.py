import datetime
import math
from os import path

from jogger.tasks import Task

from ..utils import Journal, format_duration, parse_duration_input


class Return(Exception):
    """
    Raised to trigger a return to the previous menu, or (if there is no
    previous menu) to exit the program.
    """
    
    pass


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


class SwitchingCost:
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
        
        # Verify graph_path
        try:
            graph_path = self.settings['graph_path']
        except KeyError:
            self.stderr.write('Invalid config: No graph path configured.')
            raise SystemExit(1)
        
        if not path.exists(graph_path):
            self.stderr.write('Invalid config: Graph path does not exist.')
            raise SystemExit(1)
        
        # Verify target_duration
        invalid_duration_msg = 'Invalid config: Target duration must be a positive number of minutes.'
        
        try:
            duration = self.get_target_duration()
        except ValueError:
            self.stderr.write(invalid_duration_msg)
            raise SystemExit(1)
        
        if duration < 0:
            self.stderr.write(invalid_duration_msg)
            raise SystemExit(1)
        
        # Verify switching_cost
        try:
            self.get_switching_cost()
        except ValueError as e:
            self.stderr.write(str(e))
            raise SystemExit(1)
    
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
            except Return:
                # The handler's process was interrupted in order to
                # return to the menu
                pass
    
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
        
        if not journal:
            journal = Journal(self.settings['graph_path'], date)
        
        switching_cost = self.get_switching_cost()
        
        try:
            journal.parse(switching_cost)
        except FileNotFoundError:
            self.stdout.write(f'No journal found for {journal.date}', style='error')
            return None
        
        if show_summary:
            self.show_journal_summary(journal)
        
        return journal
    
    def get_target_duration(self):
        """
        Return the configured target duration in seconds.
        """
        
        duration = int(self.settings.get('target_duration', self.DEFAULT_TARGET_DURATION))
        
        return duration * 60  # convert from minutes to seconds
    
    def get_switching_cost(self):
        """
        Return a ``SwitchingCost`` object for the calculation of estimated
        switching costs based on task durations.
        """
        
        cost_setting = self.settings.get('switching_cost', self.DEFAULT_SWITCHING_COST)
        
        return SwitchingCost(cost_setting, self.SWITCHING_COST_DURATION_RANGE)
    
    def show_journal_summary(self, journal):
        """
        Display a summary of the given `Journal` object's contents, including
        any problems detected while parsing it.
        """
        
        self.stdout.write(f'\nRead journal for: {journal.date}', style='label')
        
        num_tasks = self.styler.label(len(journal.tasks))
        self.stdout.write(f'Found {num_tasks} unlogged tasks')
        
        if not journal.tasks:
            self.stdout.write('Nothing to report', style='warning')
            return
        
        switching_cost_str = self.styler.label(journal.properties['switching-cost'])
        self.stdout.write(f'\nEstimated context switching cost: {switching_cost_str}')
        
        if journal.catch_all_block:
            cost_inclusion_str = self.styler.success('(including switching cost)')
        else:
            cost_inclusion_str = self.styler.error('(not including switching cost)')
        
        total_duration = journal.properties['total-duration']
        total_duration_str = self.styler.label(total_duration)
        self.stdout.write(f'Total duration (rounded): {total_duration_str} {cost_inclusion_str}')
        
        # Calculate the "slack time" based on the target duration and the
        # total duration of all tasks
        target_duration = self.get_target_duration()
        slack_time = max(target_duration - parse_duration_input(total_duration), 0)
        if slack_time > 0:
            slack_time_str = self.styler.warning(format_duration(slack_time))
        else:
            slack_time_str = self.styler.label('None! You work too hard.')
        
        self.stdout.write(f'Slack time: {slack_time_str}')
        
        problems = journal.problems
        if problems:
            self.stdout.write('')  # blank line
            
            for level, msg in problems:
                if level == 'error':
                    styler = self.styler.error
                elif level == 'warning':
                    styler = self.styler.warning
                else:
                    styler = self.styler.label
                
                prefix = styler(f'[{level.upper()}]')
                self.stdout.write(f'{prefix} {msg}')
    
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
            ('[unimplemented] Update journal', self.handle_log_work__update_journal, handler_args),
            ('Re-parse journal', self.parse_journal, handler_args)
        )
    
    def handle_log_work__show_worklog(self, journal):
        
        if not journal.tasks:
            self.stdout.write('\nJournal contains no tasks to summarise', style='warning')
            return
        
        self.stdout.write('\nWorklog summary:\n', style='label')
        
        make_red = self.styler.error
        
        for task in journal.tasks:
            errors = task.validate()
            
            task_id = task.task_id
            if not task_id:
                task_id = '???'
            
            if 'task_id' in errors and 'keyword' not in errors:
                task_id = make_red(task_id)
            
            duration = task.get_total_duration()
            if not duration:
                duration = '???'
            else:
                duration = format_duration(duration)
            
            if 'duration' in errors and 'keyword' not in errors:
                duration = make_red(duration)
            
            output = f'{task_id}: {duration}'
            description = task.sanitised_content
            if description:
                output = f'{output}; {description}'
            
            if 'keyword' in errors:
                output = make_red(output)
            
            extra_lines = '\n'.join(task.get_all_extra_lines())
            if extra_lines:
                output = f'{output}\n{extra_lines}'
            
            self.stdout.write(output)
    
    def handle_log_work__submit_worklog(self, journal):
        
        if not journal.tasks:
            self.stdout.write('\nJournal contains no tasks to submit', style='warning')
            return
        
        self.stdout.write(
            '\nIf you continue, the tasks in this journal will be submitted to'
            ' Jira as worklog entries. The journal file will then be updated to'
            ' reflect any processing performed by this program, flag the tasks'
            ' as done, and note the details of the submission.'
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
    
    def handle_log_work__update_journal(self, journal):
        
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
