import datetime
from os import path

from jogger.tasks import Task

from ..exceptions import ParseError, Return
from ..utils import format_duration, parse_journal


class SeqTask(Task):
    
    help = (
        'Begin the Logseq/Jira interactive integration program. This program '
        'provides several commands for synchronising Logseq and Jira.'
    )
    
    def handle(self, **options):
        
        while True:
            try:
                handler = self.show_main_menu()
            except Return:
                # The main menu was used to exit the program
                self.stdout.write('\nExiting...')
                raise SystemExit()
            
            try:
                handler()
            except Return:
                # The handler's process was interrupted in order to return to
                # the main menu
                pass
    
    def get_journal_from_date(self, date):
        
        try:
            graph_path = self.settings['graph_path']
        except KeyError:
            self.stderr.write('Invalid config: No graph path configured.')
            raise SystemExit(1)
        
        if not path.exists(graph_path):
            self.stderr.write('Invalid config: Graph path does not exist.')
            raise SystemExit(1)
        
        journal = None
        
        try:
            journal = parse_journal(graph_path, date)
        except FileNotFoundError:
            self.stdout.write(f'No journal found for {date}', style='error')
        except ParseError as e:
            self.stdout.write(f'Error parsing journal for {date}: {e}', style='error')
            raise Return()
        
        return journal
    
    def get_switching_cost(self):
        
        error = 'Invalid config: Switching cost must be a positive integer.'
        
        try:
            cost = int(self.settings.get('switching_cost', 0))
        except ValueError:
            self.stderr.write(error)
            raise SystemExit(1)
        
        if cost < 0:
            self.stderr.write(error)
            raise SystemExit(1)
        
        return cost
    
    def show_menu(self, return_option, *other_options):
        
        for i, option in enumerate(other_options, start=1):
            label = option[0]
            self.stdout.write(f'{i}. {label}')
        
        self.stdout.write(f'0. {return_option}')
        
        handler = None
        while not handler:
            try:
                selection = input('\nChoose an option: ')
            except KeyboardInterrupt:
                selection = 0
            
            try:
                selection = int(selection)
                if selection == 0:
                    raise Return()
                
                handler = other_options[selection - 1][1]
            except (ValueError, IndexError):
                self.stdout.write('Invalid selection.', style='error')
        
        return handler
    
    def show_main_menu(self):
        
        self.stdout.write('\nChoose one of the following commands to execute:', style='label')
        
        return self.show_menu(
            'Exit (or Ctrl+C)',
            ('Log work to Jira', self.log_work),
        )
    
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
            
            journal = self.get_journal_from_date(date)
        
        self.stdout.write(f'\nRead journal for: {date}', style='label')
        
        switching_cost = self.get_switching_cost()
        tasks, total_duration, total_switching_cost = journal.process_tasks(date, switching_cost)
        
        num_tasks = self.styler.label(len(tasks))
        self.stdout.write(f'Found {num_tasks} unlogged tasks')
        
        switching_cost_str = self.styler.label(format_duration(total_switching_cost))
        self.stdout.write(f'\nEstimated context switching cost: {switching_cost_str}')
        
        if journal.catch_all_block:
            cost_inclusion_str = self.styler.success('(including switching cost)')
        else:
            cost_inclusion_str = self.styler.error('(not including switching cost)')
        
        total_duration_str = self.styler.label(format_duration(total_duration))
        self.stdout.write(f'Total duration (rounded): {total_duration_str} {cost_inclusion_str}')
        
        self.stdout.write('\nJournal options:', style='label')
        
        handler = self.show_menu(
            'Return to main menu',
            
            # TODO: Show summary and return to this menu
            ('Show worklog summary', lambda: print('"worklog summary"')),
            
            # TODO: Submit via API and show prompt to mark all tasks as done
            ('Submit worklog', lambda: print('submitted!')),
            
            # TODO: Mark all tasks as done and show prompt "hit ENTER to return to main menu"
            ('Mark all tasks as done', lambda: print('all done!')),
        )
        
        handler()
