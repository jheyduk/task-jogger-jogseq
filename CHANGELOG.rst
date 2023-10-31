Change Log
==========

0.2.0 (2023-11-01)
------------------

* Journal parsing: Handle heading styles as part of task blocks
* Journal parsing: Recognise tasks using more keywords: ``NOW``, ``LATER``, ``TODO``, ``DOING``, and ``DONE``
* Journal parsing: Differentiate "worklog entries" from general tasks by the presence of a Jira issue ID (time logged against general tasks is included in the journal's total duration, but only worklog entries are submitted to Jira)
* Journal parsing: Add validation of issue IDs included in journal worklog entries to check they exist in Jira
* ``SeqTask``: Enable "Submit worklog" functionality. This menu option now submits all worklog entries in a journal to Jira.
* ``SeqTask``: Add support for setting worklog entries to ``DONE`` when marking them as logged. This can be disabled using the ``mark_done_when_logged`` setting.

0.1.0 (2023-10-20)
------------------

* Add ``SeqTask`` with initial support for parsing Logseq journals and extracting worklog info
