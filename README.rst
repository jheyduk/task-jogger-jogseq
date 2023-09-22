=========================================================
``jogseq``: A Logseq/Jira integration task for ``jogger``
=========================================================

``jogseq`` is a plugin ``jogger`` task that provides an interactive program for synchronising Logseq and Jira. `See here <https://github.com/oogles/task-jogger>`_ for details on ``jogger``.


Installation & Usage
====================

Being a plugin for ``jogger``, ``jogger`` itself also needs to be installed.

The latest stable versions of both can be installed from PyPI::

    pip install task-jogger task-jogger-jogseq

Then, create or update a relevant ``jog.py`` file to include ``SeqTask``:

.. code-block:: python
    
    # jog.py
    from jogseq.tasks import SeqTask
    
    tasks = {
        'seq': SeqTask
    }

Assuming a task name of ``seq``, as used in the above example, launch the program using ``jog``::

    $ jog seq

This will open an interactive menu, allowing you to select options by entering the corresponding number.
