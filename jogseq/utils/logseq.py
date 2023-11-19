import datetime
import os
import re

from .duration import (
    format_duration, parse_duration_input, parse_duration_timestamp,
    round_duration
)

_keywords = ('NOW', 'LATER', 'TODO', 'DOING', 'DONE')
_keywords_re = '|'.join(_keywords)

# Recognise issue IDs as one or more letters, followed by a hyphen, followed
# by one or more digits. The ID may optionally be wrapped in double square
# brackets, and optionally be followed by a colon.
# E.g. "ABC-123", "ABC-123:", "[[ABC-123]]", "[[ABC-123]]:"
_issue_id_re = r'(\[{2})?([A-Z]+-\d+)(\]{2})?:?'

# Recognise a keyword as one of "NOW", "LATER", "TODO", "DOING", or "DONE",
# followed by a space, at the beginning of the line
KEYWORD_RE = re.compile(fr'^(\s*\- )({_keywords_re}) ')

# Recognise a "task block" as one starting with a keyword, followed by a space,
# at the beginning of the line. The keyword can optionally be preceeded by any
# number of hashes, representing the block's heading level.
TASK_BLOCK_RE = re.compile(fr'^\- (\#+ )?({_keywords_re}) ')

# An an extension of a "task block", recognise an "worklog block" using the
# same rules, but also containing a Jira issue ID
WORKLOG_BLOCK_RE = re.compile(fr'^\- (\#+ )?({_keywords_re}) {_issue_id_re}')

# Recognise heading styles as any number of hashes, followed by a space,
# at the beginning of the line
HEADING_RE = re.compile(r'^\#+ ')

# Recognise page links as any text wrapped in double square brackets
LINK_RE = re.compile(r'\[\[(.*?)\]\]')

# Recognise tags as any word following a non-escaped hash. A "word" can be
# any group of characters excluding spaces (indicating the end of the tag)
# or other hashes (indicating a heading).
TAG_RE = re.compile(r'(?<!\\)(#[^# ]+)')

# When content lines are trimmed (e.g. when displayed in error messages),
# trim to this length
BLOCK_CONTENT_TRIM_LENGTH = 50


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


def escape(content):
    """
    Escape a line parsed from a Logseq markdown file, nullifying elements of
    Logseq-specific syntax. Escaped lines can be written back to Logseq and
    appear as per the original, without being recognised as special syntax.
    """
    
    content = KEYWORD_RE.sub(r'\1\\\2 ', content)
    content = TAG_RE.sub(r'\\\1', content)
    
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


class BlockProblem(Exception):
    
    def __init__(self, type, message, level='error', line=''):
        
        self.type = type
        self.message = message
        self.level = level
        self.line = line
        
        super().__init__(level, type, message, line)
    
    def __str__(self):
        
        return self.get_log_message()
    
    def get_log_message(self, styler=None):
        
        prefix = f'[{self.level.upper()}]'
        message = self.message
        
        if self.line:
            message = f'{message} for line "{self.line}"'
        
        if styler:
            styler = getattr(styler, self.level, styler.label)
            prefix = styler(prefix)
        
        return f'{prefix} {message}'


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
            if '=>' not in self.content:
                duration = 0
            else:
                duration_str = self.content.split('=>')[1].strip()
                duration = parse_duration_timestamp(duration_str)
            
            self._duration = duration
        
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
    
    def __init__(self, content, parent=None):
        
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
                raise BlockProblem(
                    type='property',
                    level='warning',
                    message=(
                        f'Duplicate property "{key}" for block "{self.trimmed_content}".'
                        f' Only the first "{key}" property will be retained.'
                    )
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
            # Logbook timers started and stopped in the same second do not
            # record a duration. They don't need to be processed or reproduced,
            # they can be ignored. However, running timers also won't yet have
            # a duration, but should be retained.
            if '=>' in content or self.keyword in ('NOW', 'DOING'):
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
        except ValueError:
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
        Validate the block's content and return a list of BlockProblem
        instances, if any. Each instance represents a problem of a certain
        type:
        
        * ``'keyword'``: Errors that relate to the task keyword, such as the
          logbook timer still running.
        * ``'issue_id'``: Errors that relate to the issue ID, such as not being
          found in Jira.
        * ``'duration'``: Errors that relate to the work logged against the
          task, such as there not being any work logged at all.
        
        :param jira: A ``Jira`` instance for querying Jira via API.
        :return: The error list.
        """
        
        errors = []
        
        def add_error(error_type, error):
            
            errors.append(BlockProblem(error_type, error, line=self.trimmed_content))
        
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
            # In addition to updating the `keyword` attribute, also replace
            # the keyword in the block's actual content, so that it gets
            # written back to the markdown file correctly
            self.content = self.content.replace(self.keyword, 'DONE', 1)
            self.keyword = 'DONE'


class Page(Block):
    """
    A parsed Logseq page.
    
    Pages are much the same as regular blocks, except they don't have a
    primary content line. Most other features are applicable: continuation
    lines, properties, child blocks, etc. Pages cannot also be tasks.
    
    Pages are responsible for parsing their own markdown file, and can also
    write back to their markdown file, persisting any changes made to the page
    and its child blocks programmatically.
    """
    
    subdirectory = 'pages'
    
    def __init__(self, graph_path, title):
        
        super().__init__(content='', parent=None)
        
        self.title = title
        self.path = os.path.join(graph_path, self.subdirectory, f'{title}.md')
        
        self._problems = None
        self._validated = False
    
    @property
    def problems(self):
        """
        A list of ``BlockProblem`` instances describing problems present
        in the page.
        """
        
        if not self._validated:
            raise Exception('Page not validated.')
        
        return self._problems
    
    def parse(self):
        """
        Using the page's configured base graph path and title, locate and
        parse the markdown file, and populate the page's attributes with
        the parsed data.
        """
        
        # In the event of re-parsing the page, reset all relevant attributes
        self.properties = {}
        self.continuation_lines = []
        self.children = []
        self._problems = []
        
        # Set a dummy indent level for the page itself to simplify the
        # comparisons in the below parsing iteration
        self.indent = -1
        
        current_block = self
        
        with open(self.path, 'r') as f:
            for line in f.readlines():
                indent = line.count('\t')
                content = line.strip()
                
                if not content.startswith('-'):
                    # The line is a continuation of the current block
                    try:
                        current_block.add_line(content)
                    except BlockProblem as e:
                        self._problems.append(e)
                    
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
                
                current_block = block_cls(content, parent_block)
                
                # Annotate the block with its indent level, to use in the
                # above comparisons on the next iteration
                current_block.indent = indent
    
    def validate(self):
        """
        Validate the page's content and populate the `problems` property with
        any problems that are found.
        """
        
        # Do nothing by default except flag the Page has having been validated
        self._validated = True
    
    def write_back(self):
        """
        Using the page's configured base graph path and title, write back to
        the corresponding markdown file.
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


class Journal(Page):
    """
    A parsed Logseq journal for a given date.
    
    In addition to just parsing basic Page features like properties and child
    blocks, Journals also collate and process the task and worklog blocks
    they contain.
    This processing includes:
    
    * Calculating the total duration of work logged to the journal's tasks.
    * Calculating the total estimated context switching cost of the journal's
      tasks, based on the duration of those tasks and a given sliding scale of
      per-task switching costs.
    * Tracking an optional "miscellaneous" worklog block, to which the estimated
      context switching cost can be logged. Only a single miscellaneous worklog
      block can exist per journal.
    """
    
    subdirectory = 'journals'
    
    def __init__(self, graph_path, date, switching_scale, jira):
        
        super().__init__(graph_path, title=date.strftime('%Y_%m_%d'))
        
        self.date = date
        self.switching_scale = switching_scale
        self.jira = jira
        
        self._misc_block = None
        self._tasks = None
        
        self.is_fully_logged = False
        self.total_duration = None
        self.unloggable_duration = None
        self.total_switching_cost = None
    
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
            problems.append(BlockProblem(
                type='misc',
                level='warning',
                message=(
                    'Only a single miscellaneous block is supported per journal.'
                    ' Subsequent miscellaneous blocks have no effect.'
                )
            ))
        
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
        
        # In the event of re-parsing the journal, reset all relevant attributes
        self._misc_block = None
        self._tasks = []
        self.is_fully_logged = False
        self.total_duration = None
        self.unloggable_duration = None
        self.total_switching_cost = None
        
        super().parse()
        
        #
        # Process the parsed tasks/worklogs to:
        # * Calculate the total duration of work logged
        # * Calculate the total estimated context switching cost, based on
        #   the duration of the tasks and a sliding scale of switching costs,
        #   represented by the given `switching_scale`.
        # * Convert any `time::` properties on the tasks into logbook entries.
        #
        
        date = self.date
        all_tasks = self._tasks = find_tasks(self)
        misc_block = self.misc_block
        
        total_duration = 0
        unloggable_duration = 0
        total_switching_cost = 0
        switching_scale = self.switching_scale
        
        for task in all_tasks:
            # Convert any time:: properties to logbook entries as long as the
            # task isn't a previously-logged worklog entry
            if 'logged' not in task.properties:
                task.convert_time_property(date)
            
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
        
        self.total_switching_cost = total_switching_cost
        self.unloggable_duration = unloggable_duration
        self.total_duration = total_duration
    
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
            problems.append(BlockProblem(
                type='property',
                message=(
                    'Invalid journal properties.'
                    ' Either all or none of the "time-logged", "total-duration",'
                    ' and "switching-cost" properties must be present.'
                )
            ))
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
            problems.append(BlockProblem(
                type='property',
                message=(
                    'Invalid "time-logged" property.'
                    ' Expected a datetime in the format "YYYY-MM-DD HH:MM:SS".'
                )
            ))
        
        try:
            duration = parse_duration_input(self.properties['total-duration'])
        except ValueError:
            valid = False
            problems.append(BlockProblem(
                type='property',
                message=(
                    'Invalid "total-duration" property.'
                    ' Expected a duration in human-friendly shorthand.'
                )
            ))
        else:
            self.total_duration = duration
        
        try:
            switching_cost = parse_duration_input(self.properties['switching-cost'])
        except ValueError:
            valid = False
            problems.append(BlockProblem(
                type='property',
                message=(
                    'Invalid "switching-cost" property.'
                    ' Expected a duration in human-friendly shorthand.'
                )
            ))
        else:
            self.total_switching_cost = switching_cost
        
        # Consider the journal fully logged if all properties are present and valid
        self.is_fully_logged = valid
        
        return valid
    
    def validate(self):
        
        valid = self._validate_properties()
        
        # If the properties aren't valid, skip validating tasks
        if valid:
            problems = self._problems
            
            for entry in self.worklogs:
                # Ignore problems in previously-logged entries
                if 'logged' not in entry.properties:
                    problems.extend(entry.validate(self.jira))
            
            if self.total_switching_cost > 0 and not self.misc_block:
                problems.insert(0, BlockProblem(
                    type='misc',
                    level='warning',
                    message=(
                        'No miscellaneous block found to log context switching'
                        ' cost against.'
                    )
                ))
        
        super().validate()
    
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
