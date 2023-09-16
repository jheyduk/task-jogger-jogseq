from jogger.tasks import LintTask
from jogger.tasks._release import ReleaseTask

tasks = {
    'lint': LintTask,
    'release': ReleaseTask
}
