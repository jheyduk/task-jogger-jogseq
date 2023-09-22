import os


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


class Block:
    
    def __init__(self, indent, content, parent=None):
        
        self.indent = indent
        self.parent = parent
        
        self.content = content.replace('-', '', 1).strip()
        
        self.extra_lines = []
        self.children = []
        
        if parent:
            parent.children.append(self)
    
    def add_line(self, content):
        
        self.extra_lines.append(content.strip())
    
    def get_tasks(self):
        
        tasks = []
        for child in self.children:
            if isinstance(child, Task):
                tasks.append(child)
            
            tasks.extend(child.get_tasks())
        
        return tasks


class Task(Block):
    
    pass


class Journal(Block):
    
    def __init__(self):
        
        super().__init__(indent=-1, content='', parent=None)
        
        self._catch_all_block = None
    
    @property
    def catch_all_block(self):
        
        return self._catch_all_block
    
    @catch_all_block.setter
    def catch_all_block(self, block):
        
        if self._catch_all_block and self._catch_all_block is not block:
            # The journal already has a catch-all task registered, and it is
            # different to the one given
            raise Exception('Only one CATCH-ALL block is supported.')
        
        self._catch_all_block = block
