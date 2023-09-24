import datetime
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


def parse_duration_timestamp(timestamp_str):
    
    # Extract hours, minutes, and seconds from the string in H:M:S format,
    # and cast as integers
    hours, minutes, seconds = map(int, timestamp_str.split(':'))
    
    # Convert the duration into seconds
    return hours * 3600 + minutes * 60 + seconds


def round_duration(total_seconds):
    
    interval = 60 * 5  # 5 minutes
    
    # If a zero duration, report it as such. But for other durations less
    # than the interval, report the interval as a minimum instead.
    if not total_seconds:
        return 0
    elif total_seconds < interval:
        return interval
    
    # Round to the most appropriate 5-minute interval
    base, remainder = divmod(total_seconds, interval)
    
    duration = interval * base
    
    # If more than 90 seconds into the next interval, round up
    if remainder > 90:
        duration += interval
    
    return duration


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


class LogbookEntry:
    
    @classmethod
    def from_duration(cls, date, duration):
        
        # Fudge some timestamps and format a compatible logbook entry based
        # on the duration
        start_time = datetime.datetime(date.year, month=date.month, day=date.day, hour=0, minute=0)
        end_time = start_time + datetime.timedelta(seconds=duration)
        
        date_format = '%Y-%m-%d %a %H:%M:%S'
        start_time_str = start_time.strftime(date_format)
        end_time_str = end_time.strftime(date_format)
        
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return cls(f'CLOCK: [{start_time_str}]--[{end_time_str}] => {hours:02}:{minutes:02}:{seconds:02}')
    
    def __init__(self, content):
        
        self.content = content
        self._duration = None
    
    @property
    def duration(self):
        
        if self._duration is None:
            duration_str = self.content.split('=>')[1].strip()
            self._duration = parse_duration_timestamp(duration_str)
        
        return self._duration


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
    
    def __init__(self, *args, **kwargs):
        
        super().__init__(*args, **kwargs)
        
        self.logbook = []
    
    def _process_new_line(self, content):
        
        content = super()._process_new_line(content)
        
        # Ignore logbook start/end entries
        if content in (':LOGBOOK:', ':END:'):
            return None
        elif content and content.startswith('CLOCK:'):
            # Logbook timers started and stopped in the same second do
            # not record a duration. They don't need to be processed or
            # reproduced, they can be ignored.
            if '=>' in content:
                self.logbook.append(LogbookEntry(content))
            
            return None
        
        return content
    
    def add_to_logbook(self, date, duration):
        
        entry = LogbookEntry.from_duration(date, duration)
        
        self.logbook.insert(0, entry)
    
    def get_total_duration(self):
        
        total = sum(log.duration for log in self.logbook)
        
        return round_duration(total)


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
        
        # Calculate and log context switching cost (in seconds)
        total_switching_cost = round_duration((num_tasks * switching_cost) * 60)
        catch_all_block = self.catch_all_block
        if catch_all_block:
            catch_all_block.add_to_logbook(date, total_switching_cost)
        
        # Calculate the total duration. Will include switching cost if a
        # catch-all task exists to log it against.
        total_duration = sum(t.get_total_duration() for t in all_tasks)
        
        return all_tasks, total_duration, total_switching_cost
