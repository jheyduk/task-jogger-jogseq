import datetime
import os
import re

# Recognise issue IDs as one or more letters, followed by a hyphen, followed
# by one or more digits. The ID may optionally be wrapped in double square
# brackets, and optionally be followed by a colon.
# E.g. "ABC-123", "ABC-123:", "[[ABC-123]]", "[[ABC-123]]:"
_issue_id_re = r'(\[{2})?([A-Z]+-\d+)(\]{2})?:?'

# Recognise a "task block" as one starting with a keyword ("NOW", "LATER",
# "TODO", "DOING", or "DONE"), followed by a space, at the beginning of the
# line. The keyword can optionally be preceeded by any number of hashes,
# representing the block's heading level.
TASK_BLOCK_RE = re.compile(r'^\- (\#+ )?(NOW|LATER|TODO|DOING|DONE) ')

# An an extension of a "task block", recognise an "worklog block" using the
# same rules, but also containing a Jira issue ID
WORKLOG_BLOCK_RE = re.compile(fr'^\- (\#+ )?(NOW|LATER|TODO|DOING|DONE) {_issue_id_re}')

# Recognise heading styles as any number of hashes, followed by a space,
# at the beginning of the line
HEADING_RE = re.compile(r'^\#+ ')

# Recognise page links as any text wrapped in double square brackets
LINK_RE = re.compile(r'\[\[(.*?)\]\]')

# When content lines are trimmed (e.g. when displayed in error messages),
# trim to this length
BLOCK_CONTENT_TRIM_LENGTH = 50


class DurationContext:
    """
    An object containing context around how duration-related operations should
    be performed. The context can be updated to affect the operations globally.
    """
    
    # Possible rounding intervals. Each interval is a two-tuple of the
    # interval in seconds, and the number of seconds into the next interval
    # that a duration must be before it is rounded up.
    ONE_MINUTE = (60, 30)
    FIVE_MINUTES = (300, 90)
    
    rounding_interval = FIVE_MINUTES


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
    Round the given number of seconds as dictated by ``DurationContext`` and
    return the new value in seconds. Values will never be rounded down to 0,
    and values that are already 0 will never be rounded up.
    
    :param total_seconds: The duration to round, in seconds.
    :return: The rounded value, in seconds.
    """
    
    interval, rounding_point = DurationContext.rounding_interval
    
    # If a zero duration, report it as such. But for other durations less
    # than the interval, report the interval as a minimum instead.
    if not total_seconds:
        return 0
    elif total_seconds < interval:
        return interval
    
    # Round to the most appropriate interval
    base, remainder = divmod(total_seconds, interval)
    
    duration = interval * base
    
    # Round up if the remainder is at or over the rounding point
    if remainder >= rounding_point:
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
        # The most common unit is minutes, so for durations of zero, report
        # it as 0 minutes.
        return '0m'
    
    return ' '.join(parts)


def sanitise(content):
    """
    Sanitise a line parsed from a Logseq markdown file, removing certain
    Logseq-specific formatting elements.
    """
    
    # Remove heading styles
    content = HEADING_RE.sub('', content)
    
    # Remove links (wrapping double square brackets)
    content = LINK_RE.sub(r'\1', content)
    
    return content


def find_tasks(block):
    """
    Return a list of the task blocks nested under the given ``Block`` instance,
    by recursively iterating through its children.
    
    :param block: The ``Block`` instance.
    :return: The list of found ``TaskBlock`` instances.
    """
    
    matches = []
    for child in block.children:
        if isinstance(child, TaskBlock):
            matches.append(child)
        
        matches.extend(find_tasks(child))
    
    return matches


def find_by_property(block, property_name):
    """
    Return a list of the blocks nested under the given ``Block`` instance
    that have a property with the given name, by recursively iterating
    through its children.
    
    :param block: The ``Block`` instance.
    :param property_name: The name of the property to search for.
    :return: The list of found ``Block`` instances.
    """
    
    matches = []
    for child in block.children:
        if property_name in child.properties:
            matches.append(child)
        
        matches.extend(find_by_property(child, property_name))
    
    return matches


def get_block_class(content):
    """
    Return the most suitable Block subclass for the given content line.
    """
    
    block_cls = Block
    if WORKLOG_BLOCK_RE.match(content):
        block_cls = WorkLogBlock
    elif TASK_BLOCK_RE.match(content):
        block_cls = TaskBlock
    
    return block_cls


class ParseError(Exception):
    """
    Raised when an unresolvable issue is encountered when parsing a journal.
    """
    
    pass


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
        
        return cls(f'CLOCK: [{start_time_str}]--[{end_time_str}] =>  {hours:02}:{minutes:02}:{seconds:02}')
    
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
    
    is_simple_block = True
    
    def __init__(self, indent, content, parent=None):
        
        self.indent = indent
        self.parent = parent
        
        self.content = content.replace('-', '', 1).strip()
        
        self.properties = {}
        self.continuation_lines = []
        self.children = []
        
        if parent:
            parent.children.append(self)
    
    @property
    def trimmed_content(self):
        """
        A version of the block's main content line that is trimmed to a
        maximum length. Useful to identify the line without displaying its
        entire content, e.g. in error messages.
        """
        
        trim_length = BLOCK_CONTENT_TRIM_LENGTH
        
        if len(self.content) > trim_length:
            return f'{self.content[:trim_length - 1]}…'
        
        return self.content
    
    @property
    def sanitised_content(self):
        """
        A version of the block's main content line that is sanitised to remove
        certain Logseq-specific formatting elements.
        """
        
        return sanitise(self.content)
    
    def _process_new_line(self, content):
        
        if content and content.split()[0].endswith('::'):
            # The line is a property of the block
            key, value = content.split('::', 1)
            
            if key in self.properties:
                raise ParseError(
                    f'Duplicate property "{key}" for block "{self.trimmed_content}". '
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
            self.continuation_lines.append(content)
    
    def get_property_lines(self):
        
        lines = []
        
        for key, value in self.properties.items():
            lines.append(f'{key}:: {value}')
        
        return lines
    
    def get_all_extra_lines(self, use_indentation=True, simple_output=True):
        """
        Return a list of all "extra" lines of content for the block, beyond its
        main content line, including:
        
        * Any continuation lines
        * Any properties
        * Any child blocks, recursively
        
        :param use_indentation: Whether to include indentation in the returned
            lines. Set to False to return top-level extra lines without
            indentation. This does not propagate to child blocks (if they have
            their own extra lines, those will be indented).
        :param simple_output: Whether to generate simpler versions of the
            returned lines. Simple outputs sanitise lines to remove certain
            Logseq-specific formatting elements, and don't include properties.
        
        :return: A list of strings, each representing an "extra" line in the block.
        """
        
        lines = []
        
        continuation_indent = ''
        child_indent = ''
        if use_indentation:
            continuation_indent = '  '
            child_indent = '  ' if simple_output else '\t'
        
        # Add any property lines (non-simple output only)
        if not simple_output:
            for line in self.get_property_lines():
                lines.append(f'{continuation_indent}{line}')
        
        # Add any continuation lines
        for line in self.continuation_lines:
            line = f'{continuation_indent}{line}'
            if simple_output:
                line = sanitise(line)
            
            lines.append(line)
        
        # Add any child blocks (and their extra lines)
        for child_block in self.children:
            # Skip non-simple child blocks when generating simple output
            if simple_output and not child_block.is_simple_block:
                continue
            
            child_content = child_block.sanitised_content if simple_output else child_block.content
            lines.append(f'{child_indent}- {child_content}')
            
            # Get all the child's extra lines as well. Propagate `simple_output`,
            # but not `use_indentation` - even if indentation is excluded at the
            # top level, it is needed at the child level to properly indicate
            # nesting.
            child_lines = child_block.get_all_extra_lines(simple_output=simple_output)
            for line in child_lines:
                lines.append(f'{child_indent}{line}')
        
        return lines


class TaskBlock(Block):
    
    is_simple_block = False
    
    def __init__(self, *args, **kwargs):
        
        super().__init__(*args, **kwargs)
        
        self.logbook = []
        
        # For the purposes of the below parsing, ignore any heading styles
        # that may be present
        content = HEADING_RE.sub('', self.content)
        
        # Split content into keyword (e.g. LATER) and any optional remaining
        # content
        self.keyword, remainder = content.split(' ', 1)
        
        # Process the remaining content for any other relevant tokens and store
        # the remainder as the task description
        self.description = self._process_content(remainder)
    
    @property
    def sanitised_content(self):
        
        # The sanitised version of a task's content is just the description
        # portion, not the whole line. If the block doesn't have a description,
        # use its parent's sanitised content instead.
        description = self.description
        if not description:
            description = self.parent.sanitised_content
            
            # Strip trailing colons from a parent description, as they are
            # often used in parent blocks listing multiple related tasks
            return description.rstrip(':')
        
        return sanitise(description)
    
    def _process_content(self, content):
        
        # Do nothing by default - consider all remaining content the task
        # description. Primarily a hook for subclasses that need to extract
        # further tokens.
        return content
    
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
        Add a manual entry to the block's logbook, using the given ``date`` and
        ``duration``. Insert the entry at the beginning of the logbook, using
        fake timestamps. The duration is the important part.
        
        :param date: The date on which the logbook entry should be made.
        :param duration: The duration of the logbook entry, in seconds.
        """
        
        entry = LogbookEntry.from_duration(date, duration)
        
        self.logbook.insert(0, entry)
    
    def convert_time_property(self, date):
        """
        Convert any ``time::`` property on the block into a logbook entry,
        using the given ``date``. This allows manual task durations to be
        subsequently treated as per regular logbook durations, i.e. contribute
        to the same totals, etc.
        
        Logbook entries created from ``time::`` properties are inserted at the
        beginning of the logbook, using fake timestamps. The duration is the
        important part.
        
        Has no effect on blocks witout a ``time::`` property.
        
        :param date: The date on which the logbook entry should be made.
        """
        
        if 'time' not in self.properties:
            return
        
        time_value = self.properties['time']
        
        # If the value isn't a valid duration string, leave the property in
        # place as a flag that the worklog entry isn't valid to be logged.
        # Otherwise remove it and replace it with a logbook entry.
        try:
            time_value = parse_duration_input(time_value)
        except ParseError:
            pass
        else:
            del self.properties['time']
            self.add_to_logbook(date, time_value)
    
    def get_total_duration(self):
        """
        Calculate the total duration of work logged against this task,
        obtained by aggregating the task's logbook. Return the total, rounded
        to the most appropriate interval using ``round_duration()``.
        
        :return: The rounded total duration of work logged to the task.
        """
        
        total = sum(log.duration for log in self.logbook)
        
        return round_duration(total)
    
    def get_property_lines(self):
        
        lines = super().get_property_lines()
        
        if self.logbook:
            lines.append(':LOGBOOK:')
            
            for log in self.logbook:
                lines.append(log.content)
            
            lines.append(':END:')
        
        return lines


class WorkLogBlock(TaskBlock):
    """
    A parsed Logseq "worklog block" - a special kind of task block that
    represents a Jira issue being worked on. Worklog blocks are denoted by
    containing a Jira issue ID, and are expected to have work logged against
    them.
    
    Work can be logged either by Logseq's built-in logbook, or manual ``time::``
    properties (the latter is converted into the former when detected).
    
    Worklog blocks are considered invalid if:
    
    * Their logbook timer is still running. In order to accurately determine
      a task's total duration, all work must already be logged.
    * They are nested within another worklog block. Nested worklog blocks are
      not supported.
    * No time has been logged, either via the logbook or ``time::`` properties.
    """
    
    def _process_content(self, content):
        
        content = super()._process_content(content)
        
        # The content of a worklog block will always contain at least a token
        # resembling a Jira issue ID, as they are only created when that is the
        # case, but it may not contain any further content
        issue_id, *remainder = content.split(' ', 1)
        
        self.issue_id = issue_id.strip(':').strip('[').strip(']')
        
        return ' '.join(remainder)
    
    def validate(self, jira):
        """
        Validate the block's content and return a dictionary of errors, if any.
        
        The dictionary is keyed on the error type, one of:
        
        * ``'keyword'``: Errors that relate to the task keyword, such as the
          logbook timer still running.
        * ``'issue_id'``: Errors that relate to the issue ID, such as not being
          found in Jira.
        * ``'duration'``: Errors that relate to the work logged against the
          task, such as there not being any work logged at all.
        
        The dictionary's values are lists of the error messages that apply to
        each type.
        
        The dictionary will only contain keys for error types that actually
        apply to the block. An empty dictionary indicates no errors were
        encountered.
        
        :param jira: A ``Jira`` instance for querying Jira via API.
        :return: The errors dictionary.
        """
        
        errors = {}
        
        def add_error(error_type, error):
            
            errors.setdefault(error_type, [])
            errors[error_type].append(error)
        
        # Ensure the task's timer isn't currently running
        if self.keyword in ('NOW', 'DOING'):
            add_error('keyword', 'Running timer detected')
        
        # Ensure the block is not a child of another worklog block
        p = self.parent
        while p:
            if isinstance(p, WorkLogBlock):
                add_error('keyword', 'Nested worklog block detected')
                break
            
            p = p.parent
        
        if not jira.verify_issue_id(self.issue_id):
            add_error('issue_id', 'Issue ID not found in Jira')
        
        if not self.logbook:
            add_error('duration', 'No duration recorded')
        
        # If a type:: property remains, it's because it's in an invalid format
        if 'time' in self.properties:
            add_error('duration', 'Invalid format for "time" property')
        
        return errors
    
    def mark_as_logged(self, set_done=True):
        """
        Flag this worklog entry as having been submitted to Jira, by adding
        a ``logged::`` property. Optionally also set the task keyword to
        ``DONE``.
        
        :param set_done: Whether to set the task keyword to ``DONE``.
        """
        
        self.properties['logged'] = 'true'
        
        if set_done:
            self.keyword = 'DONE'


class Journal(Block):
    """
    A parsed Logseq journal for a given date.
    
    Journals are much the same as regular blocks, except they don't have a
    primary content line. Most other features are applicable: continuation
    lines, properties, child blocks, etc. Journals cannot also be tasks.
    
    Journals are responsible for parsing their own markdown file, and for
    collating and processing the task and worklog blocks contained within.
    This processing includes:
    
    * Calculating the total duration of work logged to the journal's tasks.
    * Calculating the total estimated context switching cost of the journal's
      tasks, based on the duration of those tasks and a given sliding scale of
      per-task switching costs.
    * Tracking an optional "miscellaneous" worklog block, to which the estimated
      context switching cost can be logged. Only a single miscellaneous worklog
      block can exist per journal.
    
    Journals can also write back to their markdown file, persisting any changes
    made to the journal and its child blocks, including added properties,
    additional logbook entries, etc.
    """
    
    def __init__(self, graph_path, date, switching_scale, jira):
        
        super().__init__(indent=-1, content='', parent=None)
        
        self.date = date
        self.path = os.path.join(graph_path, 'journals', f'{date:%Y_%m_%d}.md')
        self.switching_scale = switching_scale
        self.jira = jira
        
        self._misc_block = None
        self._problems = None
        self._tasks = None
        
        self.is_fully_logged = False
        self.total_duration = None
        self.unloggable_duration = None
        self.total_switching_cost = None
    
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
    def misc_block(self):
        """
        A special worklog block to which the estimated context switching cost
        can be logged.
        """
        
        if self._misc_block is not None:
            return self._misc_block
        
        problems = self._problems
        if problems is None:
            raise Exception('Journal not parsed.')
        
        matches = find_by_property(self, 'misc')
        
        if not matches:
            return None
        
        if len(matches) > 1:
            problems.append(('warning', (
                'Only a single miscellaneous block is supported per journal. '
                'Subsequent miscellaneous blocks have no effect.'
            )))
        
        self._misc_block = matches[0]
        
        return self._misc_block
    
    @property
    def tasks(self):
        """
        A list of all tasks present in the journal.
        """
        
        if self._tasks is None:
            raise Exception('Journal not parsed.')
        
        return self._tasks
    
    @property
    def worklogs(self):
        """
        A list of all worklog tasks present in the journal.
        """
        
        return [t for t in self.tasks if isinstance(t, WorkLogBlock)]
    
    @property
    def logged_worklogs(self):
        """
        A list of all worklogs present in the journal that have been marked as
        logged (i.e. have a `logged::` property).
        """
        
        return [wl for wl in self.worklogs if 'logged' in wl.properties]
    
    @property
    def unlogged_worklogs(self):
        """
        A list of all worklogs present in the journal that have not been marked
        as logged (i.e. do not have a `logged::` property).
        """
        
        return [wl for wl in self.worklogs if 'logged' not in wl.properties]
    
    def parse(self):
        """
        Using the journal's configured base graph path and date, locate and
        parse the markdown file for the matching Logseq journal entry. Parsing
        this file populates the journal's attributes with the parsed data.
        """
        
        # In the event of re-parsing the journal, reset all relevant attributes
        self.properties = {}
        self.continuation_lines = []
        self.children = []
        self._misc_block = None
        self._problems = []
        self._tasks = []
        self.is_fully_logged = False
        self.total_duration = None
        self.unloggable_duration = None
        self.total_switching_cost = None
        
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
                
                block_cls = get_block_class(content)
                
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
        
        valid = self._validate_properties()
        
        if valid:
            self._process_tasks()
    
    def _validate_properties(self):
        """
        Verify that expected journal properties, such as ``time-logged::`` and
        ``total-duration::`` are valid. Invalid properties indicate they were
        incorrectly added or modified manually, and should render the journal
        as a whole invalid until they are corrected.
        
        :return: ``True`` if the journal's properties are valid, ``False`` otherwise.
        """
        
        problems = self._problems
        
        has_time = 'time-logged' in self.properties
        has_duration = 'total-duration' in self.properties
        has_switching = 'switching-cost' in self.properties
        
        # The journal is only valid if either all of the above are present,
        # or none of them are
        presences = tuple(filter(None, (has_time, has_duration, has_switching)))
        all_absent = len(presences) == 0
        all_present = len(presences) == 3
        if not all_absent and not all_present:
            problems.append(('error', (
                'Invalid journal properties.'
                ' Either all or none of the "time-logged", "total-duration",'
                ' and "switching-cost" properties must be present.'
            )))
            return False
        
        # No further validation is required if none of the properties are present
        if all_absent:
            return True
        
        # When they are present, their values must be valid
        valid = True
        
        try:
            datetime.datetime.strptime(self.properties['time-logged'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            valid = False
            problems.append(('error', (
                'Invalid "time-logged" property.'
                ' Expected a datetime in the format "YYYY-MM-DD HH:MM:SS".'
            )))
        
        try:
            duration = parse_duration_input(self.properties['total-duration'])
        except ParseError:
            valid = False
            problems.append(('error', (
                'Invalid "total-duration" property.'
                ' Expected a duration in human-friendly shorthand.'
            )))
        else:
            self.total_duration = duration
        
        try:
            switching_cost = parse_duration_input(self.properties['switching-cost'])
        except ParseError:
            valid = False
            problems.append(('error', (
                'Invalid "switching-cost" property.'
                ' Expected a duration in human-friendly shorthand.'
            )))
        else:
            self.total_switching_cost = switching_cost
        
        # Consider the journal fully logged if all properties are present and valid
        self.is_fully_logged = valid
        
        return valid
    
    def _process_tasks(self):
        """
        Process the tasks present in the journal, performing several
        calculations and transformations:
        
        * Calculate the total duration of work logged to the journal's tasks.
        * Calculate the total estimated context switching cost of the journal's
          tasks, based on the duration of those tasks and a sliding scale of
          switching costs, represented by the given ``switching_cost``.
        * Convert any ``time::`` properties on the tasks into logbook entries.
        * Validate the tasks and compile a list of any errors encountered.
        
        :param switching_cost: A ``SwitchingCost`` object for calculating
            estimated context switching costs per task, based on their duration.
        """
        
        date = self.date
        
        problems = self._problems
        all_tasks = self._tasks = find_tasks(self)
        misc_block = self.misc_block
        
        total_duration = 0
        unloggable_duration = 0
        total_switching_cost = 0
        switching_scale = self.switching_scale
        
        for task in all_tasks:
            # Perform some extra processing for tasks that aren't yet logged
            if 'logged' not in task.properties:
                # Convert any time:: properties to logbook entries
                task.convert_time_property(date)
                
                if isinstance(task, WorkLogBlock):
                    # Add any errors with the worklog definition to the
                    # journal's overall list of problems
                    errors = task.validate(self.jira)
                    for messages in errors.values():
                        for msg in messages:
                            problems.append(('error', f'{msg} for line "{task.trimmed_content}"'))
            
            # Regardless of whether the task is logged or not, still include
            # it in totals calculations
            
            # Taking into account any above-converted time:: properties,
            # calculate the task's duration and add it to the journal's
            # total duration
            task_duration = task.get_total_duration()
            total_duration += task_duration
            
            if not isinstance(task, WorkLogBlock):
                # If the task is not a worklog, add its duration to the
                # journal's total unloggable duration
                unloggable_duration += task_duration
            
            # Also calculate the task's switching cost, ignoring the misc task,
            # if any. Do NOT add to the journal's total duration at this point,
            # as the total switching cost will be rounded at the end and added
            # to the total duration then.
            if task is not misc_block:
                total_switching_cost += switching_scale.for_duration(task_duration)
        
        if total_switching_cost > 0:
            # Round the switching cost and add it to the journal's total duration
            total_switching_cost = round_duration(total_switching_cost)
            total_duration += total_switching_cost
            
            # Add the estimated switching cost to the misc block's logbook,
            # if any, so it can be allocated to a relevant Jira issue
            if misc_block:
                misc_block.add_to_logbook(date, total_switching_cost)
            else:
                problems.insert(0, (
                    'warning',
                    'No miscellaneous block found to log context switching cost against.'
                ))
        
        self.total_switching_cost = total_switching_cost
        self.unloggable_duration = unloggable_duration
        self.total_duration = total_duration
    
    def set_fully_logged(self, update_worklogs=True, set_done=True):
        """
        Add the three core journal properties indicating a fully-logged journal:
        ``time-logged::``, ``total-duration::``, and ``switching-cost::``.
        By default, also mark all currently unlogged worklog blocks in the
        journal (if any) as logged, by adding a ``logged:: true`` property to
        them. This can be disabled by passing ``update_worklogs=False``.
        When marking worklog blocks as logged, by default also set flag them
        as DONE. This can be disabled by passing ``set_done=False``.
        
        :param update_worklogs: Whether to mark all currently unlogged worklog
            blocks in the journal as logged. Defaults to True.
        :param set_done: Whether to set all currently unlogged worklog blocks
            in the journal as DONE. Only applicable when `update_worklogs=True`.
            Defaults to True.
        """
        
        # Optionally mark all unlogged worklog blocks as logged
        if update_worklogs:
            for block in self.unlogged_worklogs:
                block.mark_as_logged(set_done=set_done)
        
        # Record total duration and total switching cost as journal properties
        self.properties['total-duration'] = format_duration(self.total_duration)
        self.properties['switching-cost'] = format_duration(self.total_switching_cost)
        
        # Record the current timestamp as the time the journal was logged
        self.properties['time-logged'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def write_back(self):
        """
        Using the journal's configured base graph path and date, write back to
        the corresponding markdown file for the matching Logseq journal entry.
        This persists all modifications made to the Journal and its child
        blocks, including added properties, additional logbook entries, etc.
        """
        
        with open(self.path, 'w') as f:
            # The journal's extra lines include its own properties and
            # continuation lines, but also its children, recursively -
            # effectively the journal's entire content.
            # Passing `use_indentation=False` ensures the journal's top-level
            # properties, continuation lines, and blocks are not indented, but
            # nested children are.
            # Passing `simple_output=False` includes all elements of each
            # child block in full - nothing is skipped or sanitised as it
            # is for short task descriptions.
            for line in self.get_all_extra_lines(use_indentation=False, simple_output=False):
                f.write(f'{line}\n')
