from PySide6.QtWidgets import QDialog, QListWidget, QDialogButtonBox, QVBoxLayout, QTextEdit

class BenchmarkDialog(QDialog):
    def __init__(self, models, runner):
        super().__init__()
        self.setWindowTitle("Benchmark Models")
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        for m in models:
            self.list_widget.addItem(m)
        layout.addWidget(self.list_widget)
        self.output = QTextEdit()
        layout.addWidget(self.output)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        buttons.accepted.connect(self.run)
        buttons.rejected.connect(self.reject)

        self.runner = runner
        self.models = models

    def run(self):
        selected = [i.text() for i in self.list_widget.selectedItems()]
        text = "Enter prompt..."
        results = self.runner(text, selected)
        self.output.setPlainText(str(results))
