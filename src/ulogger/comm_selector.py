import serial.tools.list_ports
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Header, Footer, Label, ListItem, ListView, Static
from typing import Optional


def list_comports():
    """List all sorted COM ports."""
    return sorted([p.device for p in serial.tools.list_ports.comports()],
                    key=lambda x: int(''.join(filter(str.isdigit, x)) or 0))


class PortSelectionDialog(ModalScreen[Optional[str]]):
    """A modal dialog to select a COM port."""

    DEFAULT_CSS = """
    PortSelectionDialog {
        align: center middle;
    }

    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 0 1;
        width: 60;
        height: 20;
        border: thick $background 80%;
        background: $surface;
    }

    #title {
        column-span: 2;
        height: 1;
        width: 1fr;
        content-align: center middle;
        color: $text;
    }

    #port-list {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        border: solid $primary;
    }

    #buttons {
        column-span: 2;
        height: 3;
        width: 1fr;
    }

    #buttons Horizontal {
        width: 1fr;
        height: 1fr;
        align: center middle;
    }

    Button {
        width: 12;
        margin: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.selected_port: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the dialog."""
        ports = list_comports()

        with Vertical(id="dialog"):
            yield Static("Select COM Port", id="title")

            if ports:
                with ListView(id="port-list"):
                    for port in ports:
                        yield ListItem(Label(port))
            else:
                yield Static("No COM ports available", id="port-list")

            with Vertical(id="buttons"):
                with Horizontal():
                    yield Button("OK", id="ok", variant="primary")
                    yield Button("Exit", id="exit", variant="error")

    @on(ListView.Selected)
    def on_port_selected(self, event: ListView.Selected) -> None:
        """Handle port selection."""
        if event.item and event.item.children:
            label = event.item.children[0]
            if isinstance(label, Label):
                self.selected_port = label.renderable

    @on(Button.Pressed, "#ok")
    def on_ok_pressed(self) -> None:
        """Handle OK button press."""
        if self.selected_port:
            self.dismiss(self.selected_port)
        else:
            # If no port selected, try to select the first one if available
            ports = list_comports()
            if ports:
                self.dismiss(ports[0])
            else:
                self.dismiss(None)

    @on(Button.Pressed, "#exit")
    def on_exit_pressed(self) -> None:
        """Handle Exit button press."""
        self.dismiss(None)

