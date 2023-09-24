import os

from .exceptions import ParseError


def parse_journal(graph_path, date):
    
    journal_path = os.path.join(graph_path, 'journals', f'{date:%Y_%m_%d}.md')
    
    journal = Journal()
    current_block = journal
    
    with open(journal_path, 'r') as f:
        for line in f.readlines():
            indent = line.count('\t')
            content = line.strip()
            
            if not content.startswith('-'):
                # The line is a continuation of the current block
                current_block.add_line(content)
                continue
            
            block_cls = Block
            if content.startswith('- NOW ') or content.startswith('- LATER '):
                block_cls = Task
            
            if indent > current_block.indent:
                # The line is a child block of the current block
                parent_block = current_block
            elif indent == current_block.indent:
                # The line is a sibling block of the current block
                parent_block = current_block.parent
            else:
                # The line is a new block at a higher level than the
                # current block. Step back through the current block's
                # parents to the appropriate level and add a new child
                # block there.
                while indent <= current_block.indent:
                    current_block = current_block.parent
                
                parent_block = current_block
            
            current_block = block_cls(indent, content, parent_block)
            
            if '[CATCH-ALL]' in current_block.content:
                journal.catch_all_block = current_block
    
    return journal


def format_duration(total_seconds):
    
    # Calculate hours, minutes, and seconds
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Create the formatted duration string
    parts = []
    if hours > 0:
        parts.append(f'{hours}h')
    if minutes > 0:
        parts.append(f'{minutes}m')
    if seconds > 0 or not parts:
        parts.append(f'{seconds}s')
    
    return ' '.join(parts)


class Block:
    
    def __init__(self, indent, content, parent=None):
        
        self.indent = indent
        self.parent = parent
        
        self.content = content.replace('-', '', 1).strip()
        
        self.properties = {}
        self.extra_lines = []
        self.children = []
        
        if parent:
            parent.children.append(self)
    
    def _process_new_line(self, content):
        
        if content and content.split()[0].endswith('::'):
            # The line is a property of the block
            key, value = content.split('::', 1)
            
            if key in self.properties:
                raise ParseError(f'Duplicate property "{key}" for block "{self.content}".')
            
            self.properties[key] = value.strip()
            return None
        
        return content
    
    def add_line(self, content):
        
        content = content.strip()
        
        content = self._process_new_line(content)
        
        if content is not None:  # allow blank lines, just not explicitly nullified lines
            self.extra_lines.append(content)


class Task(Block):
    
    pass


class Journal(Block):
    
    def __init__(self):
        
        super().__init__(indent=-1, content='', parent=None)
        
        self._catch_all_block = None
        self._tasks = None
    
    @property
    def catch_all_block(self):
        
        return self._catch_all_block
    
    @catch_all_block.setter
    def catch_all_block(self, block):
        
        if self._catch_all_block and self._catch_all_block is not block:
            # The journal already has a catch-all task registered, and it is
            # different to the one given
            raise ParseError('Only a single CATCH-ALL block is supported per journal.')
        
        self._catch_all_block = block
    
    @property
    def tasks(self):
        
        if self._tasks is None:
            raise Exception('Tasks not collated. Call process_tasks() first.')
        
        return self._tasks
    
    def process_tasks(self, date, switching_cost):
        
        def find_tasks(block):
            tasks = []
            for child in block.children:
                if isinstance(child, Task):
                    tasks.append(child)
                
                tasks.extend(find_tasks(child))
            
            return tasks
        
        all_tasks = self._tasks = find_tasks(self)
        num_tasks = len(all_tasks)
        
        total_duration = 0  # TODO: Calculate
        total_switching_cost = (num_tasks * switching_cost) * 60  # in seconds
        
        return all_tasks, total_duration, total_switching_cost
