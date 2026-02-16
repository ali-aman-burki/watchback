from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QProgressDialog, QMessageBox
from PySide6.QtCore import Qt

class TaskWorker(QThread):
	progress = Signal(int)
	finished = Signal()
	error = Signal(str)

	def __init__(self, task_fn, *args, **kwargs):
		super().__init__()
		self.task_fn = task_fn
		self.args = args
		self.kwargs = kwargs

	def run(self):
		try:
			def progress_cb(value):
				self.progress.emit(value)

			self.task_fn(*self.args, progress_cb=progress_cb, **self.kwargs)
			self.finished.emit()
		except Exception as e:
			self.error.emit(str(e))

def run_with_progress(parent, task_fn, *args, **kwargs):
    dlg = QProgressDialog("", None, 0, 100, parent)

    dlg.setLabel(None)
    dlg.setCancelButton(None)
    dlg.setWindowTitle("")
    dlg.setMinimumSize(300, 25)
    dlg.setMaximumSize(300, 25)

    dlg.setWindowFlags(
        Qt.FramelessWindowHint |
        Qt.Dialog
    )
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)

    worker = TaskWorker(task_fn, *args, **kwargs)
    dlg.worker = worker

    worker.progress.connect(dlg.setValue)

    finished_once = {"done": False}

    def on_finished():
        if finished_once["done"]:
            return
        finished_once["done"] = True
        dlg.setValue(100)
        dlg.close()

    def on_error(msg):
        dlg.close()
        QMessageBox.warning(parent, "Error", msg)

    worker.finished.connect(on_finished)
    worker.error.connect(on_error)

    worker.start()
    dlg.exec()
    worker.wait()

