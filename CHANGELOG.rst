Change Log
==========

0.2.0 (unreleased)
------------------

* Journal parsing: Handle heading styles as part of task blocks
* Journal parsing: Recognise tasks using more keywords: ``NOW``, ``LATER``, ``TODO``, ``DOING``, and ``DONE``
* Journal parsing: Differentiate "worklog entries" from general tasks by the presence of a Jira issue ID (time logged against general tasks is included in the journal's total duration, but only worklog entries are submitted to Jira)
* Journal parsing: Add validation of issue IDs included in journal worklog entries to check they exist in Jira

0.1.0 (2023-10-20)
------------------

* Add ``SeqTask`` with initial support for parsing Logseq journals and extracting worklog info
