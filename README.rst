=========================================================
``jogseq``: A Logseq/Jira integration task for ``jogger``
=========================================================

``jogseq`` is a plugin ``jogger`` task that provides an interactive program for synchronising Logseq and Jira.

Check out the ``jogger`` project `on GitHub <https://github.com/oogles/task-jogger>`_ or `read the documentation <https://task-jogger.readthedocs.io/en/stable/>`_ for details on ``jogger``.

``jogseq`` provides support for the following, each of which is `covered in more detail <#features>`_ below:

* Logging work to Jira as issue worklog entries
* Summarising Logseq journals within a date range
* More features TBA

Also be sure to check out the `assumptions it makes <#assumptions>`_ and assess whether it suits your workflow.


Installation
============

The latest stable version of ``jogseq`` can be installed from PyPI::

    pip install task-jogger-jogseq

The following dependencies will also be installed:

* ``jogger``: The underlying task running system that ``jogseq`` is built on. See: https://github.com/oogles/task-jogger.
* ``jira``: A Python API package for Jira. See: https://github.com/pycontribs/jira.


Configuration
=============

``jogseq`` can be configured using `any compatible config file <https://task-jogger.readthedocs.io/en/stable/topics/config.html>`_ recognised by ``jogger``.

The following settings are required:

* ``graph_path``: The path to your Logseq graph. This should be the root directory of your graph, i.e. the directory containing the ``pages`` and ``journal`` directories.
* ``jira_url``: The URL of your Jira instance. E.g. ``https://mycompany.atlassian.net``.
* ``jira_user``: Your Jira username/email address.

The following optional settings are also available (see `Features`_ for details on how and when to use them):

* ``jira_api_token``: Your `Jira API token <https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/>`_. If not specified, you will be prompted for it when the program is launched. While using this setting adds convenience by avoiding the prompt on every launch, it is less secure as it requires storing the token in plain text.
* ``duration_interval``: The interval to round task durations to, in minutes. Defaults to ``5``. Valid options are ``5`` and ``1``.
* ``switching_cost``: The estimated cost of context switching between tasks, in minutes. By default, no switching cost will be calculated. If specified, it should be a range that spans no more than 30 minutes, e.g. ``1-15``. The switching cost per task will be based on that task's duration - the longer the task, the higher the switching cost. Any task longer than an hour will use the maximum switching cost. To use a fixed switching cost per task, specify the same value for both ends of the range, e.g. ``5-5``.
* ``target_duration``: The target total duration for each daily journal, in minutes. The durations of all tasks in the journal, plus the calculated switching cost as per the above, will be compared to this figure and the difference, if any, will be reported. Defaults to ``420`` (7 hours).
* ``mark_done_when_logged``: Whether to set worklog entries to ``DONE`` when they are marked as logged. Defaults to ``true``. Valid options are ``true``, ``false``, ``1``, and ``0``.
* ``min_duration_for_summary``: The minimum duration, in minutes, that a Jira issue must have in order for it to be included in a journal summary. The duration is calculated as the sum of all worklog entries against the issue within the date range being summarised. A value of ``0`` disables this feature (*all* issues with worklogs during the summary period will be included in the summary). Defaults to ``0``.

The following is a sample config file showing example configurations for the above::

    [jogger:seq]
    graph_path = /home/myuser/mygraph/
    
    jira_url = https://mycompany.atlassian.net
    jira_user = me@example.com
    jira_api_token = <token_string>
    
    duration_interval = 1
    switching_cost = 1-15
    target_duration = 450
    mark_done_when_logged = false
    
    min_duration_for_summary = 15

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

* Task blocks can use the ``NOW`` / ``LATER`` or ``TODO`` / ``DOING`` workflows, but will only be recognised as "worklog blocks" if this keyword is followed by a token looking like a Jira issue ID (one or more letters, a hyphen, then one or more numbers). It may optionally be followed by a colon, and using link syntax is supported. For example::
    
        # Valid
        NOW ABC-123 Do something
        NOW ABC-123: Do something
        NOW [[ABC-123]]: Do something
        
        # Invalid
        NOW Do something (ABC-123)
        NOW Do something #ABC-123
        NOW Do something for [[ABC-123]]

* Worklog blocks (as identified per the above) cannot be nested within each other. This prevents ambiguity when determining the total duration of the worklog entry. Nesting worklogs under regular blocks is fine, as is nesting regular blocks under worklogs (they will be included in the worklog description). Ordinary task blocks (without a Jira ID) can also be nested under worklog blocks, but will NOT be included in the worklog description, and any time logged against them will NOT be included in the worklog duration.
* Time logged against any task blocks will be recognised and included in various duration calculations, but will only be logged to Jira if recorded against worklog blocks specifically (as identified per the above).


Features
========

Logging work
------------

``jogseq`` can be used to create worklog entries against Jira issues that you track time against in Logseq. This feature works by examining a single day's journal, identifying worklog blocks, parsing their content and total duration, and then logging that time to Jira.

For a journal block to be considered a worklog valid for logging to Jira, it must:

* Use one of the ``NOW``, ``LATER``, ``TODO``, ``DOING``, or ``DONE`` keywords
* Include a Jira issue ID immediately following the keyword
* Have some time logged against it

If any issues are encountered parsing any of these values, including being missing or invalid, an error will be reported and the worklog will not be loggable. Note that any blocks with a running timer (i.e. using the ``NOW`` or ``DOING`` keywords) will also report an error and not be loggable, as their final duration is unknown.

The description used for a block's Jira worklog entry will be comprised of the block's direct content, as well as any child blocks nested under it, with the following considerations:

* The block's keyword and Jira issue ID are excluded.
* Block properties are excluded.
* Any child blocks using task keywords (e.g. ``TODO``, ``LATER``, ``DONE``, etc) are excluded.
* Any child blocks with the ``no-log::`` property are excluded. See `Ignoring child blocks`_.
* Any Logseq heading syntax will be stripped. E.g. "### Did some work" will be logged as "Did some work".
* Any Logseq link syntax will be stripped. E.g. "Meeting with [[Bob]]" will be logged as "Meeting with Bob".

When a worklog block is submitted to Jira, it will be given the ``logged:: true`` property. By default, it will also be set to ``DONE``, but this is configurable via the ``mark_done_when_logged`` setting. See `Configuration`_.

Manual durations
~~~~~~~~~~~~~~~~

To aid in logging time that *isn't* captured by Logseq's logbook functionality (perhaps because the task was only entered after time had already been spent on it, or the button to start the timer was just never pressed), ``jogseq`` supports manually specifying a duration for a task. This is done by adding a ``time::`` property to the task block.

Using the ``time::`` property is perfectly compatible with using the logbook, and the two can be used together to capture all time spent on a task. Once a ``time::`` property is parsed by ``jogseq``, it is converted to a logbook entry anyway (using fake timestamps starting from midnight of the journal's date). As such, if the parsed journal is written back to the graph, the ``time::`` property will be removed.

If specified, the ``time::`` property should use a human-readable duration shorthand, where ``h`` represents hours and ``m`` represents minutes. The value can use a mix of both. Seconds are not supported. E.g. ``time:: 10m``, ``time:: 2h``, ``time:: 1h 30m``.

Duration rounding
~~~~~~~~~~~~~~~~~

``jogseq`` will automatically round all task durations.

By default, it rounds durations to five-minute intervals. Any duration more than 90 seconds into the next interval will be rounded up, otherwise it will be rounded down. This allows for consistency with reading and reporting logged time, and more closely aligns with how work would be logged manually, when not using a timer.

However, if this is not desirable, it is also possible to configure ``jogseq`` to round durations to the nearest minute. This allows for higher accuracy if necessary. To do this, set the ``duration_interval`` setting to ``1``. See `Configuration`_.

In both configurations, durations of ``0`` are not rounded, but any duration greater than ``0`` and less than the chosen interval will always be rounded up, regardless of how close to ``0`` it is. Durations of ``0`` are not submitted to Jira.

Target duration
~~~~~~~~~~~~~~~

After parsing a journal, ``jogseq`` will display the total duration of all tasks it found, and the difference between that total and a "target duration". This can be used to see at a glance whether any additional time or tasks need to be entered into the journal before it is logged. By default, the target duration is 7 hours, but this can be configured via the ``target_duration`` setting. See `Configuration`_.

Context switching cost
~~~~~~~~~~~~~~~~~~~~~~

It is well-documented that context switching (i.e. switching between multiple tasks) is detrimental to productivity. It can also be difficult to assign a time cost to it, and track it reliably throughout the day such that it is reflected in a journal's total duration.

``jogseq`` uses a duration-based scale of context switching costs as a mechanism (albeit a simplistic and imperfect one) to help automatically track this extra time. A switching cost is calculated *per task*, where shorter tasks have lower switching costs and longer tasks have higher ones, and the total is reported for the journal as a whole. The idea is that switching between multiple quick tasks involves less overhead than switching to or from longer tasks.

The scale used to calculate switching costs can be any range of values, in minutes, that spans no more than 30 minutes in total. For example, it could be ``1-15``, ``0-30``, or ``45-75``, but could not be ``1-60``. To use the same switching cost for all tasks, specify the same value for both ends of the range, e.g. ``5-5``. Any task with a duration over an hour will use the maximum switching cost.

By default, the range is ``0-0``, effectively disabling the feature. To enable it, specify a suitable range via the ``switching_cost`` setting. See `Configuration`_.

When a valid range is specified, an estimated overall context switching cost for the journal will always be calculated, reported, and included in the journal's total duration. But it is not logged to Jira as part of individual worklog blocks. Rather, it will only be logged to Jira if a generic, "miscellaneous" worklog block is present in the journal. This block should be identified by having the ``misc:: true`` property. There should only be one such block per journal. Only the first will be recognised, any additional miscellaneous blocks will be ignored and display a warning.

Ignoring child blocks
~~~~~~~~~~~~~~~~~~~~~

``jogseq`` supports ignoring specific child blocks of a worklog block, by adding the ``no-log::`` property to them. While using ``no-log:: true`` is suggested, the property's value is not important, merely its presence.

This can be useful for excluding certain details from the Jira worklog, maybe because they are personal notes, would not be compatible, etc. Consider the following worklog block::

    - NOW ABC-123: Do a complicated thing
        - Step 1
        - Step 2
        - Step 3
        - Note to self: Never do this again.
          no-log:: true

This would result in the following Jira worklog description::
    
    Do a complicated thing
    - Step 1
    - Step 2
    - Step 3

Note that ``no-log::`` cannot be applied to a worklog block itself, only to its child blocks (it will simply be ignored). If a task block should not be logged to Jira, simply don't give it a Jira issue ID.

Repetitive tasks
~~~~~~~~~~~~~~~~

If multiple worklog blocks would use the same description, it is possible to nest them under a common parent block and have them inherit their description from it. Each individual worklog block should just leave out a description - only specifying the Jira issue ID. This can be useful in cases where the same process is applied to multiple tasks, such as code review. For example::

    - Code review:
        - LATER ABC-123
        - LATER ABC-456
        - LATER ABC-789

In this example, all three issues (``ABC-123``, ``ABC-456``, and ``ABC-789``) will be have a worklog entry submitted to Jira with "Code review" as the worklog description. The parent block itself will not be logged. Any trailing colon in the parent block's content will be stripped, but will otherwise be used verbatim.

Summarising journals
--------------------

``jogseq`` can be used to summarise work entered into journals over a given date range, to allow reviewing and reporting on work done over a period of time. By default, the date range is the last 7 days, including the current day, but program prompts allow altering the start and end dates of the range.

Once the worklog entries within each included journal are processed, the output is written to the "Worklog Digest" page of your Logseq graph. This page is created if it does not already exist.

Properties are used to annotate the page with some useful information:

* ``from-date``: The start date of the summarised date range.
* ``to-date``: The end date of the summarised date range.
* ``total-worklogs``: The total number of worklog entries within the date range.
* ``total-duration``: The total duration of all worklog entries within the date range.

Note: The ``total-worklogs`` and ``total-duration`` values will include worklog entries that were *excluded* from the summary itself, for any of the reasons covered below.

The digest itself is written as a series of nested blocks, with a top-level block for each Jira issue, and child blocks for each worklog entry for that issue, including the date on which the worklog was entered. Top-level issue blocks are given a ``duration`` property totalling the durations of all worklog entries for the issue. Durations of individual worklog entries are not reported.

To keep the digest as useful as possible, some issues or worklog entries may be excluded from it. Reasons for excluding a worklog entry may include:

* It has the ``misc`` property. Entries with this property are expected to be generic, "catch-all" entries that are not specific to any particular issue.
* It has no content. This is assumed to be because the task is simple and repetitive, and defined with the `Repetitive tasks`_ notation.

Whole issues may also be excluded from the digest, even if their individual worklog entries would otherwise have been included, for the following reasons:

* The sum of the duration of all worklog entries for the issue is less than the ``min_duration_for_summary`` setting. This setting is disabled by default (all issues will be included, regardless of duration). However, it can be configured to exclude short tasks, if such tasks are considered irrelevant for review/reporting. See `Configuration`_ for configuring ``min_duration_for_summary``.
