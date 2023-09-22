import os
import sys

from jogger.tasks import LintTask
from jogger.tasks._release import ReleaseTask
from jogger.tasks.base import TaskProxy
from jogger.utils.config import JogConf


def run_seq(settings, stdout, stderr):
    
    # Allow absolute import of the jogger_logseq_jira package, despite it not
    # being installed on the system path
    path = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, path)
    
    from jogseq.tasks import SeqTask
    
    task = TaskProxy('jog', 'seq', SeqTask, conf=JogConf())
    task.execute()  # TODO: passive=False in jogger 1.2+


tasks = {
    'seq': run_seq,
    'lint': LintTask,
    'release': ReleaseTask
}
