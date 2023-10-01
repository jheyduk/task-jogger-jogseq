import datetime
import os
import re

from .exceptions import ParseError

TASK_ID_RE = re.compile(r'^([A-Z]+-\d+):?$')


def parse_duration_timestamp(timestamp_str):
    """
    Return the number of seconds represented by the given duration timestamp
    string. The string should be in the format "H:M:S", representing the hours,
    minutes, and seconds comprising the duration.
    
    :param timestamp_str: The duration timestamp string.
    :return: The number of seconds represented by the duration timestamp string.
    """
    
    # Extract hours, minutes, and seconds from the string and cast as integers
    hours, minutes, seconds = map(int, timestamp_str.split(':'))
    
    # Convert the duration into seconds
    return hours * 3600 + minutes * 60 + seconds


def parse_duration_input(input_str):
    """
    Return the number of seconds represented by the given duration input string.
    The string should be in the format "Xh Ym", representing the hours and
    minutes comprising the duration.
    
    :param input_str: The duration input string.
    :return: The number of seconds represented by the duration input string.
    """
    
    # Extract hours and minutes from the string and cast as integers
    parts = input_str.split()
    hours, minutes = 0, 0
    for part in parts:
        if part.endswith('h'):
            hours = int(part[:-1])
        elif part.endswith('m'):
            minutes += int(part[:-1])
        else:
            raise ParseError('Invalid duration string format. Only hours and minutes are supported.')
    
    # Convert the duration into seconds
    return hours * 3600 + minutes * 60


def round_duration(total_seconds):
    """
    Round the given number of seconds to the most appropriate 5-minute interval
    and return the new value in seconds. This usually means rounding up to the
    next 5-minute interval, but the value will be rounded down if:
    
    * it is not 0 (any value over 0 is rounded up to 300, at least)
    * it is less than 90 seconds into the next interval
    
    :param total_seconds: The duration to round, in seconds.
    :return: The rounded value, in seconds.
    """
    
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
    """
    Return a human-readable string describing the given duration in hours,
    minutes, and seconds. E.g. 1h 30m.
    
    :param total_seconds: The duration, in seconds.
    :return: The string representation of the duration.
    """
    
    # Calculate hours, minutes, and seconds
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Create the formatted duration string
    parts = []
    if hours > 0:
        parts.append(f'{hours}h')
    if minutes > 0:
        parts.append(f'{minutes}m')
    if seconds > 0:
        parts.append(f'{seconds}s')
    
    if not parts:
        # The most common unit is minutes, so for durations of sero, report
        # it as 0 minutes.
        return '0m'
    
    return ' '.join(parts)


def find_tasks(block):
    """
    Return a list of the tasks nested under the given ``Block`` instance,
    by recursively iterating through its children.
    
    :param block: The ``Block`` instance.
    :return: The list of found ``Task`` instances.
    """
    
    tasks = []
    for child in block.children:
        if isinstance(child, Task):
            tasks.append(child)
        
        tasks.extend(find_tasks(child))
    
    return tasks


class LogbookEntry:
    """
    A parsed logbook entry for a Logseq block.
    """
    
    @classmethod
    def from_duration(cls, date, duration):
        """
        Create a new ``LogbookEntry`` based on the given date and duration.
        Generate some fake timestamps, starting at midnight on the given date,
        to build a compatible content line.
        
        :param date: The date on which the logbook entry should be made.
        :param duration: The duration of the logbook entry, in seconds.
        :return: The created ``LogbookEntry`` instance.
        """
        
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
        """
        The duration represented by the logbook entry, in seconds.
        """
        
        if self._duration is None:
            duration_str = self.content.split('=>')[1].strip()
            self._duration = parse_duration_timestamp(duration_str)
        
        return self._duration


class Block:
    """
    A parsed Logseq block. A block consists of:
    
    * A primary content line (can be blank).
    * Zero or more continuation lines (extra lines of content that are not
      themselves a new block).
    * Zero or more properties (key-value pairs).
    * Zero or more child blocks.
    """
    
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
                raise ParseError(
                    f'Duplicate property "{key}" for block "{self.content}". '
                    f'Only the first "{key}" property will be retained.'
                )
            
            self.properties[key] = value.strip()
            return None
        
        return content
    
    def add_line(self, content):
        """
        Add a new line of content to the block. This may be a simple
        continuation line, or contain metadata for the block (e.g. properties).
        
        :param content: The content line to add.
        """
        
        content = content.strip()
        
        content = self._process_new_line(content)
        
        if content is not None:  # allow blank lines, just not explicitly nullified lines
            self.extra_lines.append(content)


class Task(Block):
    """
    A parsed Logseq task - a special kind of block that represents a job to
    be worked on. Tasks are denoted by their content beginning with a keyword
    such as LATER, and are also expected to contain a task ID and to have work
    logged against them.
    
    Work can be logged either by Logseq's built-in logbook, or manual ``time::``
    properties (the latter is converted into the former when detected).
    
    Tasks are considered invalid if:
    
    * Their logbook timer is still running. In order to accurately determine
      a task's total duration, all work must already be logged.
    * They are nested within another task. Nested tasks are not supported.
    * Nothing resembling a task ID exists in the task's content.
    * No time has been logged, either via the logbook or ``time::`` properties.
    """
    
    def __init__(self, *args, **kwargs):
        
        super().__init__(*args, **kwargs)
        
        # Split content into keyword (e.g. LATER), task ID, and any optional
        # remaining content
        keyword, *remainder = self.content.split(' ', 2)
        
        # At least one item in the remainder should always exist, because
        # Tasks are only created if a matching keyword *followed by a space*
        # is found at the start of the line's content
        task_id = remainder[0]
        if TASK_ID_RE.match(task_id):
            # Remove the task ID from the remainder - the rest (if any) will be
            # the task description
            task_id = task_id.strip(':')
            description = remainder[1:]
        else:
            # The first item of the remainder does not appear to be a task ID,
            # consider it part of the description
            task_id = None
            description = remainder
        
        self.keyword = keyword
        self.task_id = task_id
        self.description = ' '.join(description)
        
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
        """
        Add a manual entry to the task's logbook, using the given ``date`` and
        ``duration``. Insert the entry at the beginning of the logbook, using
        fake timestamps. The duration is the important part.
        
        :param date: The date on which the logbook entry should be made.
        :param duration: The duration of the logbook entry, in seconds.
        """
        
        entry = LogbookEntry.from_duration(date, duration)
        
        self.logbook.insert(0, entry)
    
    def validate(self):
        """
        Validate the task's content and return a dictionary of errors, if any.
        
        The dictionary is keyed on the error type, one of:
        
        * ``'keyword'``: Errors that relate to the task keyword, such as the
          logbook timer still running.
        * ``'task_id'``: Errors that relate to the task ID, such as one not
          being found.
        * ``'duration'``: Errors that relate to the work logged against the
          task, such as there not being any work logged at all.
        
        The dictionary's values are lists of the error messages that apply to
        each type.
        
        The dictionary will only contain keys for error types that actually
        apply to the task. An empty dictionary indicates no errors were
        encountered.
        
        :return: The errors dictionary.
        """
        
        errors = {}
        
        def add_error(error_type, error):
            
            errors.setdefault(error_type, [])
            errors[error_type].append(error)
        
        # Ensure the task's timer isn't currently running
        if self.keyword == 'NOW':
            add_error('keyword', 'Running timer detected')
        
        # Ensure the task is not a child of another task
        p = self.parent
        while p:
            if isinstance(p, Task):
                add_error('keyword', 'Nested task detected')
                break
            
            p = p.parent
        
        # Ensure the task has an ID and a duration
        if not self.task_id:
            add_error('task_id', 'No task ID')
        
        if not self.logbook:
            add_error('duration', 'No duration recorded')
        
        # If a type:: property remains, it's because it's in an invalid format
        if 'time' in self.properties:
            add_error('duration', 'Invalid format for "time" property')
        
        return errors
    
    def get_total_duration(self):
        """
        Calculate the total duration of work logged against this task,
        obtained by aggregating the task's logbook. Return the total, rounded
        to the most appropriate interval using ``round_duration()``.
        
        :return: The rounded total duration of work logged to the task.
        """
        
        total = sum(log.duration for log in self.logbook)
        
        return round_duration(total)


class Journal(Block):
    """
    A parsed Logseq journal for a given date.
    
    Journals are much the same as regular blocks, except they don't have a
    primary content line. Most other features are applicable: continuation
    lines, properties, child blocks, etc. Journals cannot also be tasks.
    
    Journals are responsible for parsing their own markdown file, and for
    collating and processing the tasks contained within. This processing
    includes:
    
    * Calculating the total duration of work logged to the journal's tasks.
    * Calculating the total estimated context switching cost of the journal's
      tasks, based on the number of tasks and a given estimated cost per task.
    * Tracking an optional "catch-all" task, to which the estimated context
      switching cost can be logged. Only a single catch-all task can exist per
      journal.
    """
    
    def __init__(self, graph_path, date):
        
        super().__init__(indent=-1, content='', parent=None)
        
        self.date = date
        self.path = os.path.join(graph_path, 'journals', f'{date:%Y_%m_%d}.md')
        
        self._catch_all_block = None
        self._problems = None
        self._tasks = None
    
    @property
    def catch_all_block(self):
        """
        A special task block to which the estimated context switching cost
        can be logged.
        """
        
        return self._catch_all_block
    
    @catch_all_block.setter
    def catch_all_block(self, block):
        
        problems = self._problems
        if problems is None:
            raise Exception('Journal not parsed.')
        
        if self._catch_all_block and self._catch_all_block is not block:
            # The journal already has a catch-all task registered, and it is
            # different to the one given
            problems.append(('warning', (
                'Only a single CATCH-ALL block is supported per journal. '
                'Subsequent CATCH-ALL blocks have no effect.'
            )))
        
        self._catch_all_block = block
    
    @property
    def problems(self):
        """
        A list of problems present in the journal. Each item in the list is
        a two-tuple of the form ``(type, message)``, where ``type`` is one of
        ``'error'`` or ``'warning'``.
        """
        
        if self._problems is None:
            raise Exception('Journal not parsed.')
        
        return self._problems
    
    @property
    def tasks(self):
        """
        A list of all tasks present in the journal.
        """
        
        if self._tasks is None:
            raise Exception('Journal not parsed.')
        
        return self._tasks
    
    def parse(self, switching_cost):
        """
        Using the journal's configured base graph path and date, locate and
        parse the markdown file for the matching Logseq journal entry. Parsing
        this file populates the journal's attributes with the parsed data.
        
        :param switching_cost: The estimated context switching cost per task,
            in seconds.
        """
        
        # In the event of re-parsing the journal, reset all relevant attributes
        self.properties = {}
        self.extra_lines = []
        self.children = []
        self._catch_all_block = None
        self._problems = []
        self._tasks = []
        
        current_block = self
        
        with open(self.path, 'r') as f:
            for line in f.readlines():
                indent = line.count('\t')
                content = line.strip()
                
                if not content.startswith('-'):
                    # The line is a continuation of the current block
                    try:
                        current_block.add_line(content)
                    except ParseError as e:
                        self._problems.append(('warning', str(e)))
                    
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
                    self.catch_all_block = current_block
        
        self._process_tasks(switching_cost)
    
    def _process_tasks(self, switching_cost):
        """
        Process the tasks present in the journal, performing several
        calculations and transformations:
        
        * Calculate the total duration of work logged to the journal's tasks.
        * Calculate the total estimated context switching cost of the journal's
          tasks, based on the number of tasks and the given ``switching_cost``.
        * Convert any ``time::`` properties on the tasks into logbook entries.
        * Validate the tasks and compile a list of any errors encountered.
        
        :param switching_cost: The estimated context switching cost per task,
            in seconds.
        """
        
        date = self.date
        
        problems = self._problems
        all_tasks = self._tasks = find_tasks(self)
        num_tasks = len(all_tasks)
        
        # Calculate and log context switching cost (in seconds). Add it to
        # the catch-all task's logbook, if any, so it can be allocated to a
        # relevant task.
        total_switching_cost = round_duration(num_tasks * switching_cost)
        catch_all_block = self.catch_all_block
        if catch_all_block:
            catch_all_block.add_to_logbook(date, total_switching_cost)
        elif total_switching_cost > 0:
            problems.append(('warning', (
                'No CATCH-ALL task found to log context switching cost against. '
                'Not included in total duration.'
            )))
        
        # Also add a formatted version of the switching cost as a journal
        # property for future reference.
        self.properties['switching-cost'] = format_duration(total_switching_cost)
        
        for task in all_tasks:
            # Convert any time:: properties to logbook entries
            if 'time' in task.properties:
                time_value = task.properties['time']
                
                # If the value isn't a valid duration string, leave the
                # property in place as a flag that the task isn't valid to
                # be logged. Otherwise remove it and replace it with a
                # logbook entry.
                try:
                    time_value = parse_duration_input(time_value)
                except ParseError:
                    pass
                else:
                    del task.properties['time']
                    
                    # Manually-entered times are likely to be rounded already,
                    # but just in case...
                    time_value = round_duration(time_value)
                    
                    task.add_to_logbook(date, time_value)
            
            # Add any errors with the task definition to the journal's overall
            # list of problems
            errors = task.validate()
            for messages in errors.values():
                for msg in messages:
                    problems.append(('error', f'{msg} for line "{task.content}"'))
        
        # Calculate the total duration and add a formatted version to the
        # journal's properties for future reference
        total_duration = sum(t.get_total_duration() for t in all_tasks)
        self.properties['total-duration'] = format_duration(total_duration)
