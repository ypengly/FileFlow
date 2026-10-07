from PySide6.QtGui import QColor, QPalette


def apply_theme(app, dark: bool) -> None:
    app.setStyle("Fusion")
    if not dark:
        app.setPalette(app.style().standardPalette())
        return
    p = QPalette()
    c = QColor
    roles = {
        QPalette.ColorRole.Window: c(45, 45, 48), QPalette.ColorRole.WindowText: c(230, 230, 230),
        QPalette.ColorRole.Base: c(30, 30, 32), QPalette.ColorRole.AlternateBase: c(40, 40, 43),
        QPalette.ColorRole.ToolTipBase: c(60, 60, 64), QPalette.ColorRole.ToolTipText: c(230, 230, 230),
        QPalette.ColorRole.Text: c(230, 230, 230), QPalette.ColorRole.Button: c(58, 58, 62),
        QPalette.ColorRole.ButtonText: c(230, 230, 230), QPalette.ColorRole.BrightText: c(255, 80, 80),
        QPalette.ColorRole.Highlight: c(42, 130, 218), QPalette.ColorRole.HighlightedText: c(255, 255, 255),
        QPalette.ColorRole.Link: c(90, 160, 255),
    }
    for role, color in roles.items():
        p.setColor(role, color)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, c(120, 120, 120))
    app.setPalette(p)
