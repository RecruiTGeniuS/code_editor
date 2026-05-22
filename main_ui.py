# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main.ui'
##
## Created by: Qt User Interface Compiler version 6.8.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget)
import resources_from_qt_rc

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1030, 757)
        MainWindow.setMinimumSize(QSize(900, 600))
        MainWindow.setLocale(QLocale(QLocale.Russian, QLocale.Russia))
        self.styleSheet = QWidget(MainWindow)
        self.styleSheet.setObjectName(u"styleSheet")
        self.styleSheet.setStyleSheet(u"/*\n"
"Dark theme for sapr\n"
"*/\n"
"\n"
"QWidget{\n"
"	color: rgb(221, 221, 221);\n"
"	font: 10pt \"Segoe UI\";\n"
"}\n"
"\n"
"/* App backgound */\n"
"#appBg {\n"
"	background-color: rgb(49, 51, 56);\n"
"	border: 1px solid rgb(90, 90, 90);\n"
"	border-radius: 10px;\n"
"}\n"
"\n"
"/* Toggle Menu */\n"
"#leftMenuBg {\n"
"	background-color: rgb(47, 47, 52);\n"
"}\n"
"\n"
"/* Top logo */\n"
"#topLogo {\n"
"	background-color: rgb(47, 47, 52);\n"
"	background-image: url(:/Images/images/logo_medium.png);\n"
"	background-position: centered;\n"
"	background-repeat: no-repeat;\n"
"}\n"
"\n"
"/* Top text */\n"
"#titleLeftApp { font: 63 14pt \"Segoe UI Semibold\"; }\n"
"#titleLeftDescription { font: 8pt \"Segoe UI\"; color: rgb(31, 158, 235); }\n"
"\n"
"/* Top Content */\n"
"#contentTopBg {\n"
"	background-color: rgb(47, 47, 52);\n"
"	border-top-left-radius: 10px;\n"
"	border-top-right-radius: 10px;\n"
"}\n"
"#leftBox QLabel { color: rgb(235, 235, 235); padding-left: 10px; padding-right: 10px; padding-bottom: 2px;}\n"
""
                        "\n"
"/* Top menu buttons (\u0424\u0430\u0439\u043b, \u041f\u0440\u0430\u0432\u043a\u0430, ...) */\n"
"#leftBox QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"	color: rgb(180, 180, 180);\n"
"	padding: 0px 6px;\n"
"	text-align: center;\n"
"}\n"
"#leftBox QPushButton:hover {\n"
"	background-color: rgb(80, 80, 80);\n"
"	color: rgb(220, 220, 220);\n"
"}\n"
"#leftBox QPushButton:pressed {\n"
"	background-color: rgb(100, 100, 100);\n"
"	color: rgb(255, 255, 255);\n"
"}\n"
"\n"
"/* Bottom content */\n"
"#contentBottom{\n"
"	border-top: 3px solid rgb(37, 38, 43);\n"
"}\n"
"#bottomBar {\n"
"	background-color: rgb(43, 43, 48);\n"
"	border-bottom-left-radius: 10px;\n"
"	border-bottom-right-radius: 10px;\n"
"}\n"
"#bottomBar QLabel { font-size: 11px; color: rgb(235, 235, 235); padding-left: 10px; padding-right: 10px; padding-bottom: 2px; }\n"
"\n"
"\n"
"/* Menus */\n"
"#topMenu .QPushButton {\n"
"	background-position: left center;\n"
"    background-repeat: no-repeat;\n"
""
                        "	border: none;\n"
"	border-left: 15px solid transparent;\n"
"	background-color: transparent;\n"
"	text-align: left;\n"
"	font-size: 12px;\n"
"	padding-left: 40px;\n"
"}\n"
"#topMenu .QPushButton:hover {\n"
"	background-color: rgb(80, 80, 80);\n"
"}\n"
"#topMenu .QPushButton:pressed {\n"
"	background-color: rgb(100, 100, 100);\n"
"	color: rgb(255, 255, 255);\n"
"}\n"
"#bottomMenu .QPushButton {\n"
"	background-position: left center;\n"
"    background-repeat: no-repeat;\n"
"	border: none;\n"
"	border-left: 15px solid transparent;\n"
"	background-color:transparent;\n"
"	text-align: left;\n"
"	font-size: 12px;\n"
"	padding-left: 40px;\n"
"}\n"
"#bottomMenu .QPushButton:hover {\n"
"	background-color: rgb(80, 80, 80);\n"
"}\n"
"#bottomMenu .QPushButton:pressed {\n"
"	background-color: rgb(100, 100, 100);\n"
"	color: rgb(255, 255, 255);\n"
"}\n"
"\n"
"#leftMenuFrame {\n"
"	border-top: 3px solid rgb(37, 38, 43);\n"
"}\n"
"\n"
"/* Toggle Button */\n"
"#toggleButton {\n"
"	background-position: left center;\n"
"    back"
                        "ground-repeat: no-repeat;\n"
"	border: none;\n"
"	border-left: 15px solid transparent;\n"
"	background-color: rgb(47, 47, 52);\n"
"	text-align: left;\n"
"	font-size: 12px;\n"
"	padding-left: 40px;\n"
"	color: rgb(255, 255, 255);\n"
"}\n"
"#toggleButton:hover {\n"
"	background-color: rgb(80, 80, 80);\n"
"}\n"
"#toggleButton:pressed {\n"
"	background-color: rgb(100, 100, 100);\n"
"}\n"
"\n"
"/* Top Right Buttons  */\n"
"#closeAppBtn {\n"
"	background-color: rgba(255, 255, 255, 0);\n"
"	border: none;\n"
"	border-top-right-radius: 10px;\n"
"}\n"
"#closeAppBtn:hover {\n"
"	background-color: rgb(207, 144, 145);\n"
"}\n"
"#closeAppBtn:pressed {\n"
"	background-color: rgb(241, 117, 119);\n"
"}\n"
"\n"
"#maximizeRestoreAppBtn {\n"
"	background-color: rgba(255, 255, 255, 0);\n"
"	border: none;\n"
"}\n"
"#maximizeRestoreAppBtn:hover {\n"
"	background-color: rgb(80, 80, 80);\n"
"}\n"
"#maximizeRestoreAppBtn:pressed {\n"
"	background-color: rgb(100, 100, 100);\n"
"}\n"
"\n"
"#minimizeAppBtn {\n"
"	background-color: rgba(25"
                        "5, 255, 255, 0);\n"
"	border: none;\n"
"}\n"
"#minimizeAppBtn:hover {\n"
"	background-color: rgb(80, 80, 80);\n"
"}\n"
"#minimizeAppBtn:pressed {\n"
"	background-color: rgb(100, 100, 100);\n"
"}\n"
"\n"
"/* Theme for LineEdit*/\n"
"QLineEdit {\n"
"	background-color: rgb(33, 37, 43);\n"
"	border-radius: 5px;\n"
"	border: 2px solid rgb(33, 37, 43);\n"
"	padding-left: 10px;\n"
"	selection-color: rgb(255, 255, 255);\n"
"	selection-background-color: rgb(31, 158, 235);\n"
"}\n"
"QLineEdit:hover {\n"
"	border: 2px solid rgb(64, 71, 88);\n"
"}\n"
"QLineEdit:focus {\n"
"	border: 2px solid rgb(91, 101, 124);\n"
"}\n"
"\n"
"\n"
"#pagesContainer QPushButton {\n"
"	border: 2px solid rgb(52, 59, 72);\n"
"	border-radius: 5px;	\n"
"	background-color: rgb(52, 59, 72);\n"
"}\n"
"#pagesContainer QPushButton:hover {\n"
"	background-color: rgb(57, 65, 80);\n"
"	border: 2px solid rgb(61, 70, 86);\n"
"}\n"
"#pagesContainer QPushButton:pressed {\n"
"	background-color: rgb(35, 40, 49);\n"
"	border: 2px solid rgb(43, 50, 61);\n"
"}\n"
""
                        "\n"
"\n"
"/* ScrollBars */\n"
"QScrollBar:horizontal {\n"
"    border: none;\n"
"    background: rgb(52, 59, 72);\n"
"    height: 8px;\n"
"    margin: 0px 21px 0 21px;\n"
"	border-radius: 0px;\n"
"}\n"
"QScrollBar::handle:horizontal {\n"
"    background: rgb(61, 70, 86);\n"
"    min-width: 25px;\n"
"	border-radius: 4px\n"
"}\n"
"QScrollBar::add-line:horizontal {\n"
"    border: none;\n"
"    background: rgb(55, 63, 77);\n"
"    width: 20px;\n"
"	border-top-right-radius: 4px;\n"
"    border-bottom-right-radius: 4px;\n"
"    subcontrol-position: right;\n"
"    subcontrol-origin: margin;\n"
"}\n"
"QScrollBar::sub-line:horizontal {\n"
"    border: none;\n"
"    background: rgb(55, 63, 77);\n"
"    width: 20px;\n"
"	border-top-left-radius: 4px;\n"
"    border-bottom-left-radius: 4px;\n"
"    subcontrol-position: left;\n"
"    subcontrol-origin: margin;\n"
"}\n"
"QScrollBar::up-arrow:horizontal, QScrollBar::down-arrow:horizontal\n"
"{\n"
"     background: none;\n"
"}\n"
"QScrollBar::add-page:horizontal, QScrollBar::"
                        "sub-page:horizontal\n"
"{\n"
"     background: none;\n"
"}\n"
" QScrollBar:vertical {\n"
"	border: none;\n"
"    background: rgb(52, 59, 72);\n"
"    width: 8px;\n"
"    margin: 21px 0 21px 0;\n"
"	border-radius: 0px;\n"
" }\n"
" QScrollBar::handle:vertical {	\n"
"	background: rgb(61, 70, 86);\n"
"    min-height: 25px;\n"
"	border-radius: 4px\n"
" }\n"
" QScrollBar::add-line:vertical {\n"
"     border: none;\n"
"    background: rgb(55, 63, 77);\n"
"     height: 20px;\n"
"	border-bottom-left-radius: 4px;\n"
"    border-bottom-right-radius: 4px;\n"
"     subcontrol-position: bottom;\n"
"     subcontrol-origin: margin;\n"
" }\n"
" QScrollBar::sub-line:vertical {\n"
"	border: none;\n"
"    background: rgb(55, 63, 77);\n"
"     height: 20px;\n"
"	border-top-left-radius: 4px;\n"
"    border-top-right-radius: 4px;\n"
"     subcontrol-position: top;\n"
"     subcontrol-origin: margin;\n"
" }\n"
" QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {\n"
"     background: none;\n"
" }\n"
"\n"
" QScrollBar::ad"
                        "d-page:vertical, QScrollBar::sub-page:vertical {\n"
"     background: none;\n"
" }\n"
"\n"
" /* CheckBox */\n"
"QCheckBox::indicator {\n"
"    border: 2px solid rgb(37, 38, 43);\n"
"	width: 18px;\n"
"	height: 18px;\n"
"	border-radius: 10px;\n"
"    background: rgb(47, 47, 52);\n"
"}\n"
"QCheckBox::indicator:hover {\n"
"    border: 2px solid rgb(47, 52, 61);\n"
"}\n"
"QCheckBox::indicator:checked {\n"
"    background: 3px solid rgb(26, 127, 189);\n"
"	border: 2px solid rgb(37, 41, 48);	\n"
"}")
        self.styleSheet.setLocale(QLocale(QLocale.Russian, QLocale.Russia))
        self.appMargins = QHBoxLayout(self.styleSheet)
        self.appMargins.setSpacing(0)
        self.appMargins.setObjectName(u"appMargins")
        self.appMargins.setContentsMargins(0, 0, 0, 0)
        self.appBg = QFrame(self.styleSheet)
        self.appBg.setObjectName(u"appBg")
        self.appBg.setFrameShape(QFrame.Shape.NoFrame)
        self.appBg.setFrameShadow(QFrame.Shadow.Raised)
        self.appLayout = QHBoxLayout(self.appBg)
        self.appLayout.setSpacing(0)
        self.appLayout.setObjectName(u"appLayout")
        self.appLayout.setContentsMargins(0, 0, 0, 0)
        self.contentBox = QFrame(self.appBg)
        self.contentBox.setObjectName(u"contentBox")
        self.contentBox.setFrameShape(QFrame.Shape.NoFrame)
        self.contentBox.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout = QVBoxLayout(self.contentBox)
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.contentTopBg = QFrame(self.contentBox)
        self.contentTopBg.setObjectName(u"contentTopBg")
        self.contentTopBg.setMinimumSize(QSize(0, 35))
        self.contentTopBg.setMaximumSize(QSize(16777215, 35))
        self.contentTopBg.setFrameShape(QFrame.Shape.NoFrame)
        self.contentTopBg.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_3 = QHBoxLayout(self.contentTopBg)
        self.horizontalLayout_3.setSpacing(0)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.leftBox = QFrame(self.contentTopBg)
        self.leftBox.setObjectName(u"leftBox")
        self.leftBox.setFrameShape(QFrame.Shape.NoFrame)
        self.leftBox.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_5 = QHBoxLayout(self.leftBox)
        self.horizontalLayout_5.setSpacing(1)
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.horizontalLayout_5.setContentsMargins(2, 1, 1, 1)
        self.appLogo = QLabel(self.leftBox)
        self.appLogo.setObjectName(u"appLogo")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.appLogo.sizePolicy().hasHeightForWidth())
        self.appLogo.setSizePolicy(sizePolicy)
        self.appLogo.setMinimumSize(QSize(24, 24))
        self.appLogo.setMaximumSize(QSize(34, 30))
        self.appLogo.setStyleSheet(u"margin-top: 4px;")
        self.appLogo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_5.addWidget(self.appLogo)

        self.fileButton = QPushButton(self.leftBox)
        self.fileButton.setObjectName(u"fileButton")
        self.fileButton.setMinimumSize(QSize(44, 25))
        self.fileButton.setMaximumSize(QSize(44, 16777215))

        self.horizontalLayout_5.addWidget(self.fileButton)

        self.editButton = QPushButton(self.leftBox)
        self.editButton.setObjectName(u"editButton")
        self.editButton.setMinimumSize(QSize(62, 25))
        self.editButton.setMaximumSize(QSize(62, 16777215))

        self.horizontalLayout_5.addWidget(self.editButton)

        self.selectionButton = QPushButton(self.leftBox)
        self.selectionButton.setObjectName(u"selectionButton")
        self.selectionButton.setMinimumSize(QSize(80, 25))
        self.selectionButton.setMaximumSize(QSize(80, 16777215))

        self.horizontalLayout_5.addWidget(self.selectionButton)

        self.findButton = QPushButton(self.leftBox)
        self.findButton.setObjectName(u"findButton")
        self.findButton.setMinimumSize(QSize(54, 25))
        self.findButton.setMaximumSize(QSize(54, 16777215))

        self.horizontalLayout_5.addWidget(self.findButton)

        self.viewButton = QPushButton(self.leftBox)
        self.viewButton.setObjectName(u"viewButton")
        self.viewButton.setMinimumSize(QSize(42, 25))
        self.viewButton.setMaximumSize(QSize(42, 16777215))

        self.horizontalLayout_5.addWidget(self.viewButton)

        self.preferencesButton = QPushButton(self.leftBox)
        self.preferencesButton.setObjectName(u"preferencesButton")
        self.preferencesButton.setMinimumSize(QSize(80, 25))
        self.preferencesButton.setMaximumSize(QSize(80, 16777215))

        self.horizontalLayout_5.addWidget(self.preferencesButton)

        self.helpButton = QPushButton(self.leftBox)
        self.helpButton.setObjectName(u"helpButton")
        self.helpButton.setMinimumSize(QSize(62, 25))
        self.helpButton.setMaximumSize(QSize(62, 16777215))

        self.horizontalLayout_5.addWidget(self.helpButton)


        self.horizontalLayout_3.addWidget(self.leftBox, 0, Qt.AlignmentFlag.AlignLeft)

        self.rightButtons = QFrame(self.contentTopBg)
        self.rightButtons.setObjectName(u"rightButtons")
        self.rightButtons.setFrameShape(QFrame.Shape.NoFrame)
        self.rightButtons.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_4 = QHBoxLayout(self.rightButtons)
        self.horizontalLayout_4.setSpacing(0)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.horizontalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.minimizeAppBtn = QPushButton(self.rightButtons)
        self.minimizeAppBtn.setObjectName(u"minimizeAppBtn")
        self.minimizeAppBtn.setMinimumSize(QSize(40, 35))
        self.minimizeAppBtn.setMaximumSize(QSize(40, 35))
        icon = QIcon()
        icon.addFile(u":/Icons/icons/minimize.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.minimizeAppBtn.setIcon(icon)
        self.minimizeAppBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_4.addWidget(self.minimizeAppBtn)

        self.maximizeRestoreAppBtn = QPushButton(self.rightButtons)
        self.maximizeRestoreAppBtn.setObjectName(u"maximizeRestoreAppBtn")
        self.maximizeRestoreAppBtn.setMinimumSize(QSize(40, 35))
        self.maximizeRestoreAppBtn.setMaximumSize(QSize(40, 35))
        icon1 = QIcon()
        icon1.addFile(u":/Icons/icons/maximize.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.maximizeRestoreAppBtn.setIcon(icon1)
        self.maximizeRestoreAppBtn.setIconSize(QSize(20, 15))

        self.horizontalLayout_4.addWidget(self.maximizeRestoreAppBtn)

        self.closeAppBtn = QPushButton(self.rightButtons)
        self.closeAppBtn.setObjectName(u"closeAppBtn")
        self.closeAppBtn.setMinimumSize(QSize(40, 35))
        self.closeAppBtn.setMaximumSize(QSize(40, 35))
        icon2 = QIcon()
        icon2.addFile(u":/Icons/icons/close.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.closeAppBtn.setIcon(icon2)
        self.closeAppBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_4.addWidget(self.closeAppBtn)


        self.horizontalLayout_3.addWidget(self.rightButtons, 0, Qt.AlignmentFlag.AlignRight)


        self.verticalLayout.addWidget(self.contentTopBg)

        self.contentBottom = QFrame(self.contentBox)
        self.contentBottom.setObjectName(u"contentBottom")
        self.contentBottom.setFrameShape(QFrame.Shape.NoFrame)
        self.contentBottom.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_4 = QVBoxLayout(self.contentBottom)
        self.verticalLayout_4.setSpacing(0)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.verticalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.content = QFrame(self.contentBottom)
        self.content.setObjectName(u"content")
        self.content.setFrameShape(QFrame.Shape.NoFrame)
        self.content.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout = QHBoxLayout(self.content)
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.monacoContainer = QFrame(self.content)
        self.monacoContainer.setObjectName(u"monacoContainer")
        self.monacoContainer.setFrameShape(QFrame.Shape.NoFrame)
        self.monacoContainer.setFrameShadow(QFrame.Shadow.Raised)
        self.monacoContainer.setLineWidth(0)
        self.verticalLayout_5 = QVBoxLayout(self.monacoContainer)
        self.verticalLayout_5.setSpacing(0)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.verticalLayout_5.setContentsMargins(0, 0, 0, 0)
        self.tabBarContainer = QFrame(self.monacoContainer)
        self.tabBarContainer.setObjectName(u"tabBarContainer")
        self.tabBarContainer.setMinimumSize(QSize(0, 36))
        self.tabBarContainer.setMaximumSize(QSize(16777215, 36))
        self.tabBarContainer.setStyleSheet(u"background-color: rgb(43, 43, 48);")
        self.tabBarContainer.setFrameShape(QFrame.Shape.NoFrame)
        self.tabBarContainer.setFrameShadow(QFrame.Shadow.Raised)
        self.tabBarContainer.setLineWidth(0)
        self.horizontalLayout_2 = QHBoxLayout(self.tabBarContainer)
        self.horizontalLayout_2.setSpacing(0)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.arrowFrame = QFrame(self.tabBarContainer)
        self.arrowFrame.setObjectName(u"arrowFrame")
        self.arrowFrame.setMinimumSize(QSize(0, 0))
        self.arrowFrame.setMaximumSize(QSize(64, 16777215))
        self.arrowFrame.setFrameShape(QFrame.Shape.NoFrame)
        self.arrowFrame.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_arrow = QHBoxLayout(self.arrowFrame)
        self.horizontalLayout_arrow.setSpacing(2)
        self.horizontalLayout_arrow.setObjectName(u"horizontalLayout_arrow")
        self.horizontalLayout_arrow.setContentsMargins(3, 0, 3, 0)
        self.goBackBtn = QPushButton(self.arrowFrame)
        self.goBackBtn.setObjectName(u"goBackBtn")
        self.goBackBtn.setMinimumSize(QSize(28, 28))
        self.goBackBtn.setMaximumSize(QSize(28, 28))
        self.goBackBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.goBackBtn.setStyleSheet(u"QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"}\n"
"QPushButton:hover {\n"
"	background-color: rgba(255, 255, 255, 30);\n"
"}\n"
"QPushButton:pressed {\n"
"	background-color: rgba(255, 255, 255, 50);\n"
"}\n"
"QPushButton:disabled {\n"
"	background-color: transparent;\n"
"}")
        icon3 = QIcon()
        icon3.addFile(u":/Icons/icons/arrow_left.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.goBackBtn.setIcon(icon3)
        self.goBackBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_arrow.addWidget(self.goBackBtn)

        self.goForwardBtn = QPushButton(self.arrowFrame)
        self.goForwardBtn.setObjectName(u"goForwardBtn")
        self.goForwardBtn.setMinimumSize(QSize(28, 28))
        self.goForwardBtn.setMaximumSize(QSize(28, 28))
        self.goForwardBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.goForwardBtn.setStyleSheet(u"QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"}\n"
"QPushButton:hover {\n"
"	background-color: rgba(255, 255, 255, 30);\n"
"}\n"
"QPushButton:pressed {\n"
"	background-color: rgba(255, 255, 255, 50);\n"
"}\n"
"QPushButton:disabled {\n"
"	background-color: transparent;\n"
"}")
        icon4 = QIcon()
        icon4.addFile(u":/Icons/icons/arrow_right.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.goForwardBtn.setIcon(icon4)
        self.goForwardBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_arrow.addWidget(self.goForwardBtn)


        self.horizontalLayout_2.addWidget(self.arrowFrame)

        self.tabBarFrame = QFrame(self.tabBarContainer)
        self.tabBarFrame.setObjectName(u"tabBarFrame")
        self.tabBarFrame.setFrameShape(QFrame.Shape.NoFrame)
        self.tabBarFrame.setFrameShadow(QFrame.Shadow.Raised)

        self.horizontalLayout_2.addWidget(self.tabBarFrame)

        self.filesAddListFrame = QFrame(self.tabBarContainer)
        self.filesAddListFrame.setObjectName(u"filesAddListFrame")
        self.filesAddListFrame.setMinimumSize(QSize(96, 0))
        self.filesAddListFrame.setMaximumSize(QSize(96, 16777215))
        self.filesAddListFrame.setFrameShape(QFrame.Shape.NoFrame)
        self.filesAddListFrame.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_filesAddList = QHBoxLayout(self.filesAddListFrame)
        self.horizontalLayout_filesAddList.setSpacing(2)
        self.horizontalLayout_filesAddList.setObjectName(u"horizontalLayout_filesAddList")
        self.horizontalLayout_filesAddList.setContentsMargins(3, 0, 3, 0)
        self.addFileBtn = QPushButton(self.filesAddListFrame)
        self.addFileBtn.setObjectName(u"addFileBtn")
        self.addFileBtn.setMinimumSize(QSize(28, 28))
        self.addFileBtn.setMaximumSize(QSize(28, 28))
        self.addFileBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.addFileBtn.setStyleSheet(u"QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"}\n"
"QPushButton:hover {\n"
"	background-color: rgba(255, 255, 255, 30);\n"
"}\n"
"QPushButton:pressed {\n"
"	background-color: rgba(255, 255, 255, 50);\n"
"}\n"
"QPushButton:disabled {\n"
"	background-color: transparent;\n"
"}")
        icon5 = QIcon()
        icon5.addFile(u":/Icons/icons/plus.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.addFileBtn.setIcon(icon5)
        self.addFileBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_filesAddList.addWidget(self.addFileBtn)

        self.showAllFilesBtn = QPushButton(self.filesAddListFrame)
        self.showAllFilesBtn.setObjectName(u"showAllFilesBtn")
        self.showAllFilesBtn.setMinimumSize(QSize(28, 28))
        self.showAllFilesBtn.setMaximumSize(QSize(28, 28))
        self.showAllFilesBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.showAllFilesBtn.setStyleSheet(u"QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"}\n"
"QPushButton:hover {\n"
"	background-color: rgba(255, 255, 255, 30);\n"
"}\n"
"QPushButton:pressed {\n"
"	background-color: rgba(255, 255, 255, 50);\n"
"}\n"
"QPushButton:disabled {\n"
"	background-color: transparent;\n"
"}")
        icon6 = QIcon()
        icon6.addFile(u":/Icons/icons/all_files_show.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.showAllFilesBtn.setIcon(icon6)
        self.showAllFilesBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_filesAddList.addWidget(self.showAllFilesBtn)

        self.sideAiBtn = QPushButton(self.filesAddListFrame)
        self.sideAiBtn.setObjectName(u"sideAiBtn")
        self.sideAiBtn.setMinimumSize(QSize(28, 28))
        self.sideAiBtn.setMaximumSize(QSize(28, 28))
        self.sideAiBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.sideAiBtn.setStyleSheet(u"QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"}\n"
"QPushButton:hover {\n"
"	background-color: rgba(255, 255, 255, 30);\n"
"}\n"
"QPushButton:pressed {\n"
"	background-color: rgba(255, 255, 255, 50);\n"
"}\n"
"QPushButton:disabled {\n"
"	background-color: transparent;\n"
"}")
        icon7 = QIcon()
        icon7.addFile(u":/Icons/icons/side_ai.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.sideAiBtn.setIcon(icon7)
        self.sideAiBtn.setIconSize(QSize(20, 20))

        self.horizontalLayout_filesAddList.addWidget(self.sideAiBtn)


        self.horizontalLayout_2.addWidget(self.filesAddListFrame)


        self.verticalLayout_5.addWidget(self.tabBarContainer)

        self.monacoFrame = QFrame(self.monacoContainer)
        self.monacoFrame.setObjectName(u"monacoFrame")
        self.monacoFrame.setStyleSheet(u"background-color: rgb(49, 51, 56);")
        self.monacoFrame.setFrameShape(QFrame.Shape.NoFrame)
        self.monacoFrame.setFrameShadow(QFrame.Shadow.Raised)

        self.verticalLayout_5.addWidget(self.monacoFrame)


        self.horizontalLayout.addWidget(self.monacoContainer)


        self.verticalLayout_4.addWidget(self.content)

        self.bottomBar = QFrame(self.contentBottom)
        self.bottomBar.setObjectName(u"bottomBar")
        self.bottomBar.setMinimumSize(QSize(0, 22))
        self.bottomBar.setMaximumSize(QSize(16777215, 22))
        self.bottomBar.setFrameShape(QFrame.Shape.NoFrame)
        self.bottomBar.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_6 = QHBoxLayout(self.bottomBar)
        self.horizontalLayout_6.setSpacing(0)
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.horizontalLayout_6.setContentsMargins(2, 0, 0, 0)
        self.tree_side_button_frame = QFrame(self.bottomBar)
        self.tree_side_button_frame.setObjectName(u"tree_side_button_frame")
        self.tree_side_button_frame.setMinimumSize(QSize(26, 0))
        self.tree_side_button_frame.setMaximumSize(QSize(26, 16777215))
        self.tree_side_button_frame.setFrameShape(QFrame.Shape.NoFrame)
        self.tree_side_button_frame.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_treeSide = QHBoxLayout(self.tree_side_button_frame)
        self.horizontalLayout_treeSide.setSpacing(0)
        self.horizontalLayout_treeSide.setObjectName(u"horizontalLayout_treeSide")
        self.horizontalLayout_treeSide.setContentsMargins(5, 1, 1, 1)
        self.treeSideToggleBtn = QPushButton(self.tree_side_button_frame)
        self.treeSideToggleBtn.setObjectName(u"treeSideToggleBtn")
        self.treeSideToggleBtn.setMinimumSize(QSize(20, 20))
        self.treeSideToggleBtn.setMaximumSize(QSize(20, 20))
        self.treeSideToggleBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.treeSideToggleBtn.setStyleSheet(u"QPushButton {\n"
"	background-color: transparent;\n"
"	border: none;\n"
"	border-radius: 4px;\n"
"}\n"
"QPushButton:hover {\n"
"	background-color: rgba(255, 255, 255, 30);\n"
"}\n"
"QPushButton:pressed {\n"
"	background-color: rgba(255, 255, 255, 50);\n"
"}\n"
"QPushButton:disabled {\n"
"	background-color: transparent;\n"
"}")
        icon8 = QIcon()
        icon8.addFile(u":/Icons/icons/side_tree.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.treeSideToggleBtn.setIcon(icon8)
        self.treeSideToggleBtn.setIconSize(QSize(14, 14))

        self.horizontalLayout_treeSide.addWidget(self.treeSideToggleBtn)


        self.horizontalLayout_6.addWidget(self.tree_side_button_frame)

        self.filePathLabel = QLabel(self.bottomBar)
        self.filePathLabel.setObjectName(u"filePathLabel")

        self.horizontalLayout_6.addWidget(self.filePathLabel)

        self.lineColumnLabel = QLabel(self.bottomBar)
        self.lineColumnLabel.setObjectName(u"lineColumnLabel")
        self.lineColumnLabel.setMinimumSize(QSize(120, 0))

        self.horizontalLayout_6.addWidget(self.lineColumnLabel, 0, Qt.AlignmentFlag.AlignRight)

        self.languageLabel = QLabel(self.bottomBar)
        self.languageLabel.setObjectName(u"languageLabel")
        self.languageLabel.setMaximumSize(QSize(100, 16777215))

        self.horizontalLayout_6.addWidget(self.languageLabel)

        self.frame_size_grip = QFrame(self.bottomBar)
        self.frame_size_grip.setObjectName(u"frame_size_grip")
        self.frame_size_grip.setMinimumSize(QSize(20, 0))
        self.frame_size_grip.setMaximumSize(QSize(20, 16777215))
        self.frame_size_grip.setFrameShape(QFrame.Shape.NoFrame)
        self.frame_size_grip.setFrameShadow(QFrame.Shadow.Raised)

        self.horizontalLayout_6.addWidget(self.frame_size_grip)


        self.verticalLayout_4.addWidget(self.bottomBar)


        self.verticalLayout.addWidget(self.contentBottom)


        self.appLayout.addWidget(self.contentBox)


        self.appMargins.addWidget(self.appBg)

        MainWindow.setCentralWidget(self.styleSheet)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.fileButton.setText(QCoreApplication.translate("MainWindow", u"\u0424\u0430\u0439\u043b", None))
        self.editButton.setText(QCoreApplication.translate("MainWindow", u"\u041f\u0440\u0430\u0432\u043a\u0430", None))
        self.selectionButton.setText(QCoreApplication.translate("MainWindow", u"\u0412\u044b\u0434\u0435\u043b\u0435\u043d\u0438\u0435", None))
        self.findButton.setText(QCoreApplication.translate("MainWindow", u"\u041f\u043e\u0438\u0441\u043a", None))
        self.viewButton.setText(QCoreApplication.translate("MainWindow", u"\u0412\u0438\u0434", None))
        self.preferencesButton.setText(QCoreApplication.translate("MainWindow", u"\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438", None))
        self.helpButton.setText(QCoreApplication.translate("MainWindow", u"\u0421\u043f\u0440\u0430\u0432\u043a\u0430", None))
        self.minimizeAppBtn.setText("")
        self.maximizeRestoreAppBtn.setText("")
        self.closeAppBtn.setText("")
#if QT_CONFIG(tooltip)
        self.goBackBtn.setToolTip(QCoreApplication.translate("MainWindow", u"\u041d\u0430\u0437\u0430\u0434 (Alt+\u2190)", None))
#endif // QT_CONFIG(tooltip)
        self.goBackBtn.setText("")
#if QT_CONFIG(tooltip)
        self.goForwardBtn.setToolTip(QCoreApplication.translate("MainWindow", u"\u0412\u043f\u0435\u0440\u0451\u0434 (Alt+\u2192)", None))
#endif // QT_CONFIG(tooltip)
        self.goForwardBtn.setText("")
#if QT_CONFIG(tooltip)
        self.addFileBtn.setToolTip(QCoreApplication.translate("MainWindow", u"\u041d\u043e\u0432\u044b\u0439 \u0444\u0430\u0439\u043b (Ctrl+N)", None))
#endif // QT_CONFIG(tooltip)
        self.addFileBtn.setText("")
#if QT_CONFIG(tooltip)
        self.showAllFilesBtn.setToolTip(QCoreApplication.translate("MainWindow", u"\u0421\u043f\u0438\u0441\u043e\u043a \u0432\u0441\u0435\u0445 \u0444\u0430\u0439\u043b\u043e\u0432", None))
#endif // QT_CONFIG(tooltip)
        self.showAllFilesBtn.setText("")
        self.sideAiBtn.setText("")
        self.treeSideToggleBtn.setText("")
        self.filePathLabel.setText(QCoreApplication.translate("MainWindow", u"\u041f\u0443\u0442\u044c \u043a \u0444\u0430\u0439\u043b\u0443", None))
        self.lineColumnLabel.setText(QCoreApplication.translate("MainWindow", u"\u041b\u0438\u043d. _, \u0421\u0442\u043e\u043b\u0431. _", None))
        self.languageLabel.setText(QCoreApplication.translate("MainWindow", u"\u042f\u041f", None))
    # retranslateUi

