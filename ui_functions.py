from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import QSizeGrip

from custom_grips import CustomGrip
import resources_from_qt_rc  # noqa: F401


COLLAPSED_FLAG = False


class UIFunctions:
    def maximize_restore(self):
        global COLLAPSED_FLAG
        status = COLLAPSED_FLAG

        self.normal_geometry = None

        if status == False:
            self.showMaximized()
            COLLAPSED_FLAG = True
            self.ui.appMargins.setContentsMargins(0, 0, 0, 0)
            self.ui.maximizeRestoreAppBtn.setToolTip("Restore")
            self.ui.maximizeRestoreAppBtn.setIcon(QIcon(":/Icons/icons/restore.png"))
            self.ui.frame_size_grip.hide()
            self.left_grip.hide()
            self.right_grip.hide()
            self.top_grip.hide()
            self.bottom_grip.hide()
        else:
            COLLAPSED_FLAG = False
            self.showNormal()
            self.resize(self.width()+1, self.height()+1)
            self.ui.appMargins.setContentsMargins(5, 5, 5, 5)
            self.ui.maximizeRestoreAppBtn.setToolTip("Maximize")
            self.ui.maximizeRestoreAppBtn.setIcon(QIcon(":/Icons/icons/maximize.png"))
            self.ui.frame_size_grip.show()
            self.left_grip.show()
            self.right_grip.show()
            self.top_grip.show()
            self.bottom_grip.show()

    def return_status(self):
        return COLLAPSED_FLAG

    def set_status(self, status):
        global COLLAPSED_FLAG
        COLLAPSED_FLAG = status

    def apply_window_corners(self):
        # При раскрытии окна на весь экран скругления и обводка убираются,
        # т.к. окно прижато к краям монитора и круглые углы выглядят чуждо.
        is_maximized = bool(self.windowState() & Qt.WindowMaximized)
        if is_maximized:
            self.ui.appBg.setStyleSheet(
                "#appBg { border: none; border-radius: 0px; }"
            )
            self.ui.contentTopBg.setStyleSheet(
                "#contentTopBg {"
                " border-top-left-radius: 0px;"
                " border-top-right-radius: 0px; }"
            )
            self.ui.bottomBar.setStyleSheet(
                "#bottomBar {"
                " border-bottom-left-radius: 0px;"
                " border-bottom-right-radius: 0px; }"
            )
            self.ui.closeAppBtn.setStyleSheet(
                "#closeAppBtn { border-top-right-radius: 0px; }"
            )
        else:
            self.ui.appBg.setStyleSheet("")
            self.ui.contentTopBg.setStyleSheet("")
            self.ui.bottomBar.setStyleSheet("")
            self.ui.closeAppBtn.setStyleSheet("")

    def ui_definitions(self):
        def double_click_maximize_restore(event):
            if event.type() == QEvent.MouseButtonDblClick:
                QTimer.singleShot(250, lambda: UIFunctions.maximize_restore(self))
        self.ui.contentTopBg.mouseDoubleClickEvent = double_click_maximize_restore

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        def move_window(event):
            if UIFunctions.return_status(self):
                UIFunctions.maximize_restore(self)

                self.move(QCursor.pos().x() - self.width() / 2, QCursor.pos().y() - 20)

            if event.buttons() == Qt.LeftButton:
                self.move(self.pos() + event.globalPos() - self.drag_pos)
                self.drag_pos = event.globalPos()
                event.accept()

        self.ui.contentTopBg.mouseMoveEvent = move_window

        self.left_grip = CustomGrip(self, Qt.LeftEdge, True)
        self.right_grip = CustomGrip(self, Qt.RightEdge, True)
        self.top_grip = CustomGrip(self, Qt.TopEdge, True)
        self.bottom_grip = CustomGrip(self, Qt.BottomEdge, True)

        self.sizegrip = QSizeGrip(self.ui.frame_size_grip)
        self.sizegrip.setStyleSheet("width: 20px; height: 20px; margin 0px; padding: 0px;")

        self.ui.minimizeAppBtn.clicked.connect(lambda: self.showMinimized())

        self.ui.maximizeRestoreAppBtn.clicked.connect(lambda: UIFunctions.maximize_restore(self))

        self.ui.closeAppBtn.clicked.connect(lambda: self.close())

    def theme(self, file, useCustomTheme):
        if useCustomTheme:
            str = open(file, 'r').read()
            self.ui.styleSheet.setStyleSheet(str)

    def resize_grips(self):
        self.left_grip.setGeometry(0, 10, 10, self.height())
        self.right_grip.setGeometry(self.width() - 10, 10, 10, self.height())
        self.top_grip.setGeometry(0, 0, self.width(), 10)
        self.bottom_grip.setGeometry(0, self.height() - 10, self.width(), 10)
