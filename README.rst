==========================================
``jogger`` plugin: Logseq/Jira integration
==========================================

This ``jogger`` plugin provides an interactive program for synchronising Logseq and Jira. `See here <https://github.com/oogles/task-jogger>`_ for details on ``jogger``.


Installation & Usage
====================

Being a plugin for ``jogger``, ``jogger`` itself also needs to be installed.

The latest stable versions of both can be installed from PyPI::

    pip install task-jogger task-jogger-logseq-jira

Then, create or update a relevant ``jog.py`` file to include ``SeqTask``:

.. code-block:: python
    
    # jog.py
    from jogger_logseq_jira.tasks import SeqTask
    
    tasks = {
        'seq': SeqTask
    }

Assuming a task name of ``seq``, as used in the above example, launch the program using ``jog``::

    $ jog seq

This will open an interactive menu, allowing you to select options by entering the corresponding number.
