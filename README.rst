=========================================================
``jogseq``: A Logseq/Jira integration task for ``jogger``
=========================================================

``jogseq`` is a plugin ``jogger`` task that provides an interactive program for synchronising Logseq and Jira.

Check out the ``jogger`` project `on GitHub <https://github.com/oogles/task-jogger>`_ or `read the documentation <https://task-jogger.readthedocs.io/en/stable/>`_ for details on ``jogger``.

``jogseq`` provides support for the following, each of which is `covered in more detail <#features>`_ below:

* Logging work to Jira as issue worklog entries
* More features TBA

Also be sure to check out the `assumptions it makes <#assumptions>`_ and assess whether it suits your workflow.


Installation
============

Being a plugin for ``jogger``, ``jogseq`` requires ``jogger`` itself also be installed.

The latest stable versions of both can be installed from PyPI::

    pip install task-jogger task-jogger-jogseq


Configuration
=============

``jogseq`` requires the path to your Logseq graph to be configured before it can be used. This is done via the ``graph_path`` setting in a suitable ``jogger`` `config file <https://task-jogger.readthedocs.io/en/stable/topics/config.html>`_.

The following optional configuration options are also available (see `Features`_ for details on how and when to use them):

* ``duration_interval``: The interval to round task durations to, in minutes. Defaults to ``5``. Valid options are ``5`` and ``1``.
* ``target_duration``: The target total duration for each daily journal, in minutes. The durations of all tasks in the journal, plus the calculated switching cost as per the above, will be compared to this figure and the difference, if any, will be reported. Defaults to ``420`` (7 hours).
* ``switching_cost``: The estimated cost of context switching between tasks, in minutes. By default, no switching cost will be calculated. If specified, it should be a range that spans no more than 30 minutes, e.g. ``1-15``. The switching cost per task will be based on that task's duration - the longer the task, the higher the switching cost. Any task longer than an hour will use the maximum switching cost. To use a fixed switching cost per task, specify the same value for both ends of the range, e.g. ``5-5``.

The following is a sample config file showing example configurations for the above::

    [jogger:seq]
    graph_path = /home/myuser/mygraph/
    switching_cost = 1-15
    target_duration = 450

NOTE: This assumes a task name of ``seq``, though any name can be used as long as it matches the name specified in ``jog.py`` (see below).


Usage
=====

Once configured, create or update a relevant ``jog.py`` file to include ``SeqTask``:

.. code-block:: python
    
    # jog.py
    from jogseq.tasks import SeqTask
    
    tasks = {
        'seq': SeqTask
    }

Assuming a task name of ``seq``, as used in the above example, launch the program using ``jog``::

    $ jog seq

This will open an interactive menu, allowing you to select options by entering the corresponding number.


Assumptions
===========

``jogseq`` makes a number of assumptions about the structure of a Logseq journal, and the way you use it, in order to provide the featureset it does.

For logging work to Jira, the following assumptions apply:

* Tasks use the ``NOW`` / ``LATER`` workflow rather than ``TODO`` / ``DOING``. This allows for ``TODO`` tasks to be nested under ``NOW`` / ``LATER`` blocks as placeholder tasks to be completed at a later date, and not logged as part of the current journal.
* ``NOW`` / ``LATER`` tasks cannot be nested within each other. This prevents ambiguity when determining the total duration of a task (does logged time apply to the parent or child task?). Nesting tasks under regular blocks is fine, as is nesting regular blocks under tasks (they will be included in the worklog description).
* The Jira issue ID of a task must be the second token in the block (after ``NOW`` / ``LATER``). Following it with a colon is optional, and using link syntax is supported. For example::
    
        # Valid
        NOW ABC-123 Do something
        NOW ABC-123: Do something
        NOW [[ABC-123]]: Do something
        
        # Invalid
        NOW Do something (ABC-123)
        NOW Do something #ABC-123
        NOW Do something for [[ABC-123]]

* Tasks that should be logged to Jira are never marked ``DONE`` (rather, they are just left as ``LATER``). Tasks marked as ``DONE`` will be ignored. When a task is logged by ``jogseq``, it will be given the ``logged:: true`` property.


Features
========

Logging work
------------

``jogseq`` can be used to create worklog entries against Jira issues that you track time against in Logseq. This feature works by examining a single day's journal, identifying task blocks, parsing their content and total duration, and then logging that time to Jira.

For a journal block to be considered a task valid for logging to Jira, it must:

* Use one of the ``NOW`` / ``LATER`` keywords
* Include a Jira issue ID as the second token in the block
* Have some time logged against it

If any issues are encountered parsing any of these values, including any being missing entirely, an error will be reported and the task will not be loggable. Note that any blocks with a running timer (i.e. using the ``NOW`` keyword) will also report an error and not be loggable, as their final duration is unknown.

The description used for a task's Jira worklog entry will be comprised of the block's direct content, as well as any child blocks nested under it, with the following considerations:

* The ``LATER`` keyword and Jira issue ID are excluded.
* Block properties are excluded.
* Any child blocks using the ``TODO`` or ``DONE`` keywords are excluded.
* Any Logseq link syntax will be stripped. E.g. "Meeting with [[Bob]]" will be logged as "Meeting with Bob".

Manual durations
~~~~~~~~~~~~~~~~

To aid in logging time that *isn't* captured by Logseq's logbook functionality (perhaps because the task was only entered after time had already been spent on it, or the button to start the timer was just never pressed), ``jogseq`` supports manually specifying a duration for a task. This is done by adding a ``time::`` property to the task block.

Using the ``time::`` property is perfectly compatible with using the logbook, and the two can be used together to capture all time spent on a task. Once a ``time::`` property is parsed by ``jogseq``, it is converted to a logbook entry anyway (using fake timestamps starting from midnight of the journal's date). As such, if the parsed journal is written back to the graph, the ``time::`` property will be removed.

If specified, the ``time::`` property should use a human-readable duration shorthand, where ``h`` represents hours and ``m`` represents minutes. The value can use a mix of both. Seconds are not supported. E.g. ``time:: 10m``, ``time:: 2h``, ``time:: 1h 30m``.

Duration rounding
~~~~~~~~~~~~~~~~~

``jogseq`` will automatically round all task durations.

By default, it rounds durations to five-minute intervals. Any duration more than 90 seconds into the next interval will be rounded up, otherwise it will be rounded down. This helps account for additional time inevitably taken for most tasks outside the span captured by starting and stopping the timer. It also more closely aligns with how work would be logged manually, when not using a timer.

However, if this is not desirable, it is also possible to configure ``jogseq`` to round durations to the nearest minute. This allows for more accuracy if the timer is used to capture all time spent on a task. To do this, set the ``duration_interval`` setting to ``1``. See `Configuration`_.

In both configurations, durations under chosen interval will always be rounded up. Durations of 0 are not logged.

Target duration
~~~~~~~~~~~~~~~

After parsing a journal, ``jogseq`` will display the total duration of all tasks it found, and the difference between that total and a "target duration". This can be used to see at a glance whether any additional time or tasks need to be entered into the journal before it is logged. By default, the target duration is 7 hours, but this can be configured via the ``target_duration`` setting. See `Configuration`_.

Context switching cost
~~~~~~~~~~~~~~~~~~~~~~

It is well-documented that context switching (i.e. switching between multiple tasks) is detrimental to productivity. It can also be difficult to assign a time cost to it, and track it reliably throughout the day such that it is reflected in a journal's total duration.

``jogseq`` uses a duration-based scale of context switching costs as a mechanism (albeit a simplistic and imperfect one) to help automatically track this extra time. A switching cost is calculated *per task*, where shorter tasks have lower switching costs and longer tasks have higher ones, and the total is reported for the journal as a whole. The idea is that switching between multiple quick tasks involves less overhead than switching to or from longer tasks.

The scale used to calculate switching costs can be any range of values, in minutes, that spans no more than 30 minutes in total. For example, it could be ``1-15``, ``0-30``, or ``45-75``, but could not be ``1-60``. To use the same switching cost for all tasks, specify the same value for both ends of the range, e.g. ``5-5``. Any task with a duration over an hour will use the maximum switching cost.

By default, the range is ``0-0``, effectively disabling the feature. To enable it, specify a suitable range via the ``switching_cost`` setting. See `Configuration`_.

When a valid range is specified, an estimated overall context switching cost for the journal will always be calculated, reported, and included in the journal's total duration. But it is not logged to Jira as part of individual tasks. Rather, it will only be logged to Jira if a generic, "miscellaneous" task is present in the journal. This task should be identified by having the ``misc:: true`` property. There should only be one such task per journal. Only the first will be recognised, any additional miscellaneous tasks will be ignored and display a warning.

Repetitive tasks
~~~~~~~~~~~~~~~~

If multiple tasks use the same description, it is possible to nest them under a common parent block and have them inherit their description from it. Each individual task should just leave out a description - only specifying the Jira issue ID. This can be useful in cases where the same process is applied to multiple tasks, such as code review. For example::

    - Code review:
        - LATER ABC-123
        - LATER ABC-456
        - LATER ABC-789

In this example, all three tasks (``ABC-123``, ``ABC-456``, and ``ABC-789``) will be logged to Jira with the "Code review" as the worklog description. The parent block itself will not be logged. Any trailing colon in the parent block's content will be stripped, but will otherwise be used verbatim.
