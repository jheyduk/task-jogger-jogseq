import datetime

from jogger.tasks import Task


class Return(Exception):
    """
    Raised to trigger a return to the previous menu, or (if there is no
    previous menu) to exit the program.
    """
    
    pass


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
        
        self.stdout.write('\nChoose which day to log work for. Default: today.', style='label')
        self.stdout.write('Enter an offset from the current day. E.g. 0 = today, 1 = yesterday, 2 = the day before, etc.')
        
        date = None
        while not date:
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
        
        self.stdout.write(f'Reading journal for: {date}', style='label')
        print('-- read and summarise journal here --')
        
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
