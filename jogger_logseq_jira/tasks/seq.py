from jogger.tasks import Task


class SeqTask(Task):
    
    help = (
        'Begin the Logseq/Jira interactive integration program. This program '
        'provides several commands for synchronising Logseq and Jira.'
    )
    
    def handle(self, **options):
        
        self.show_main_menu()
    
    def show_menu(self, zero_option, *other_options):
        
        for i, option in enumerate(other_options, start=1):
            label = option[0]
            self.stdout.write(f'{i}. {label}')
        
        zero_label, zero_handler = zero_option
        self.stdout.write(f'0. {zero_label}')
        
        handler = None
        while not handler:
            try:
                selection = input('\nChoose an option: ')
            except KeyboardInterrupt:
                selection = 0
            
            try:
                selection = int(selection)
                if selection == 0:
                    handler = zero_handler
                else:
                    handler = other_options[selection - 1][1]
            except (ValueError, IndexError):
                self.stdout.write('Invalid selection.', style='error')
        
        handler()
    
    def show_main_menu(self):
        
        self.stdout.write('\nChoose one of the following commands to execute:', style='label')
        
        self.show_menu(
            ('Exit (or Ctrl+C)', self.exit),
            ('Log work to Jira', self.log_work),
        )
    
    def log_work(self):
        
        print('logging work')
        
        self.show_main_menu()
    
    def exit(self):
        
        self.stdout.write('\nExiting...')
        raise SystemExit()
