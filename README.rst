=========================================================
``jogseq``: A Logseq/Jira integration task for ``jogger``
=========================================================

``jogseq`` is a plugin ``jogger`` task that provides an interactive program for synchronising Logseq and Jira.

Check out the ``jogger`` project `on GitHub <https://github.com/oogles/task-jogger>`_ or `read the documentation <https://task-jogger.readthedocs.io/en/stable/>`_ for details on ``jogger``.


Installation
============

Being a plugin for ``jogger``, ``jogseq`` requires ``jogger`` itself also be installed.

The latest stable versions of both can be installed from PyPI::

    pip install task-jogger task-jogger-jogseq

Configuration
=============

``jogseq`` requires the path to your Logseq graph to be configured before it can be used. This is done via the ``graph_path`` setting in a suitable ``jogger`` `config file <https://task-jogger.readthedocs.io/en/stable/topics/config.html>`_.

The following optional configuration options are also available:

* ``switching_cost``: The estimated cost of context switching between tasks, in minutes. By default, no switching cost will be calculated. If specified, it should be a range that spans no more than 30 minutes, e.g. ``1-15``. The switching cost per task will be based on that task's duration - the longer the task, the higher the switching cost. Any task longer than an hour will use the maximum switching cost. To use a fixed switching cost per task, specify the same value for both ends of the range, e.g. ``5-5``.
* ``target_duration``: The target total duration for each daily journal, in minutes. The durations of all tasks in the journal, plus the calculated switching cost as per the above, will be compared to this figure and the difference, if any, will be reported. Defaults to ``420`` (7 hours).

The following is a sample config file showing example configurations for the above::

    [jogger:seq]
    graph_path = /home/myuser/mygraph/
    switching_cost = 1-15
    target_duration = 450

NOTE: This assumes a task name of ``'seq'``, though any name can be used as long as it matches the name specified in ``jog.py`` (see below).

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
