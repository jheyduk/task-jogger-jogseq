import datetime
from os import path

from jogger.tasks import Task

from ..exceptions import ParseError, Return
from ..utils import Journal, format_duration


class SeqTask(Task):
    
    DEFAULT_SWITCHING_COST = 0
    DEFAULT_TARGET_DURATION = 8 * 60  # 8 hours
    
    help = (
        'Begin the Logseq/Jira interactive integration program. This program '
        'provides several commands for synchronising Logseq and Jira.'
    )
    
    def handle(self, **options):
        
        try:
            graph_path = self.settings['graph_path']
        except KeyError:
            self.stderr.write('Invalid config: No graph path configured.')
            raise SystemExit(1)
        
        if not path.exists(graph_path):
            self.stderr.write('Invalid config: Graph path does not exist.')
            raise SystemExit(1)
        
        try:
            self.show_menu(
                '\nChoose one of the following commands to execute:',
                'Exit (or Ctrl+C)',
                ('Log work to Jira', self.log_work)
            )
        except Return:
            # The main menu was used to exit the program
            self.stdout.write('\nExiting...')
            raise SystemExit()
    
    def show_menu(self, intro, return_option, *other_options):
        
        while True:
            self.stdout.write(intro, style='label')
            
            for i, option in enumerate(other_options, start=1):
                label = option[0]
                self.stdout.write(f'{i}. {label}')
            
            self.stdout.write(f'0. {return_option}')
            
            handler = None
            args = ()
            while not handler:
                try:
                    selection = input('\nChoose an option: ')
                except KeyboardInterrupt:
                    selection = 0
                
                try:
                    selection = int(selection)
                    if selection == 0:
                        raise Return()
                    
                    selection = other_options[selection - 1]
                except (ValueError, IndexError):
                    self.stdout.write('Invalid selection.', style='error')
                else:
                    handler = selection[1]
                    try:
                        args = selection[2]
                    except IndexError:  # args are optional
                        pass
            
            try:
                handler(*args)
            except Return:
                # The handler's process was interrupted in order to
                # return to the menu
                pass
    
    def parse_journal(self, journal=None, date=None, show_summary=True):
        
        if not journal and not date:
            raise TypeError('One of "journal" or "date" must be provided.')
        
        if not journal:
            journal = Journal(self.settings['graph_path'], date)
        
        try:
            journal.parse()
        except FileNotFoundError:
            self.stdout.write(f'No journal found for {journal.date}', style='error')
            return None
        except ParseError as e:
            self.stdout.write(f'Error parsing journal for {journal.date}: {e}', style='error')
            raise Return()
        
        if show_summary:
            self.show_journal_summary(journal)
        
        return journal
    
    def get_target_duration(self):
        
        error = 'Invalid config: Target duration must be a positive integer.'
        
        try:
            duration = int(self.settings.get('target_duration', self.DEFAULT_TARGET_DURATION))
        except ValueError:
            self.stderr.write(error)
            raise SystemExit(1)
        
        if duration < 0:
            self.stderr.write(error)
            raise SystemExit(1)
        
        return duration * 60  # convert from minutes to seconds
    
    def get_switching_cost(self):
        
        error = 'Invalid config: Switching cost must be a positive integer.'
        
        try:
            cost = int(self.settings.get('switching_cost', self.DEFAULT_SWITCHING_COST))
        except ValueError:
            self.stderr.write(error)
            raise SystemExit(1)
        
        if cost < 0:
            self.stderr.write(error)
            raise SystemExit(1)
        
        return cost * 60  # convert from minutes to seconds
    
    def show_journal_summary(self, journal):
        
        self.stdout.write(f'\nRead journal for: {journal.date}', style='label')
        
        target_duration = self.get_target_duration()
        switching_cost = self.get_switching_cost()
        result = journal.process_tasks(target_duration, switching_cost)
        
        num_tasks = self.styler.label(len(result['tasks']))
        self.stdout.write(f'Found {num_tasks} unlogged tasks')
        
        switching_cost_str = self.styler.label(format_duration(result['total_switching_cost']))
        self.stdout.write(f'\nEstimated context switching cost: {switching_cost_str}')
        
        if journal.catch_all_block:
            cost_inclusion_str = self.styler.success('(including switching cost)')
        else:
            cost_inclusion_str = self.styler.error('(not including switching cost)')
        
        total_duration_str = self.styler.label(format_duration(result['total_duration']))
        self.stdout.write(f'Total duration (rounded): {total_duration_str} {cost_inclusion_str}')
        
        slack_time_str = self.styler.label(format_duration(result['slack_time']))
        self.stdout.write(f'Slack time: {slack_time_str}')
        
        log = result['log']
        if log:
            self.stdout.write('')  # blank line
            
            for level, msg in log:
                if level == 'error':
                    styler = self.styler.error
                elif level == 'warning':
                    styler = self.styler.warning
                else:
                    styler = self.styler.label
                
                prefix = styler(f'[{level.upper()}]')
                self.stdout.write(f'{prefix} {msg}')
    
    def log_work(self):
        
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
            
            # TODO: Show summary and return to this menu
            ('Show worklog summary', lambda j: print(f'"worklog summary" for {id(j)}'), handler_args),
            
            # TODO: Submit via API and show prompt to mark all tasks as done
            ('Submit worklog', lambda: print('submitted!')),
            
            # TODO: Mark all tasks as done and show prompt "hit ENTER to return to main menu"
            ('Mark all tasks as done', lambda: print('all done!')),
            
            ('Re-parse journal', self.parse_journal, handler_args)
        )
