"""Textual renderer for YAML materials."""

from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
)
from textual.worker import Worker, WorkerState

from jobctl.generation.renderer import (
    RESUME_SECTION_DEFAULTS,
    build_resume_context,
    infer_template_name,
    list_template_names,
    load_material,
    output_pdf_path,
    render_pdf,
    validate_material,
)
from jobctl.generation.schemas import ResumeYAML


@dataclass(frozen=True)
class MaterialRenderResult:
    output_path: Path | None
    rendered: bool


class MaterialRenderApp(App[MaterialRenderResult]):
    """Interactive section picker for rendering a resume YAML file."""

    CSS = """
    Screen {
        background: #f6f8f7;
        color: #202522;
    }
    Header {
        background: #1f4d46;
        color: #ffffff;
    }
    Footer {
        background: #202522;
        color: #f6f8f7;
    }
    #root {
        height: 1fr;
        padding: 1 2;
    }
    #path {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        background: #e5eeeb;
        color: #202522;
        text-style: bold;
    }
    #body {
        height: 1fr;
    }
    #sections {
        width: 46;
        padding: 1;
        background: #ffffff;
        border: solid #7a8f89;
    }
    #details {
        width: 1fr;
        padding: 1 2;
        margin-left: 1;
        background: #ffffff;
        border: solid #7a8f89;
        color: #202522;
    }
    #actions {
        height: auto;
        margin-top: 1;
    }
    #section-title {
        text-style: bold;
        color: #1f4d46;
        margin-bottom: 1;
    }
    #template-title {
        text-style: bold;
        color: #1f4d46;
        margin: 1 0 1 0;
    }
    #output-title {
        text-style: bold;
        color: #1f4d46;
        margin: 1 0 1 0;
    }
    Input {
        background: #f6f8f7;
        color: #202522;
        border: tall #7a8f89;
    }
    Input:focus {
        border: tall #1f4d46;
    }
    ListView {
        height: auto;
        background: #ffffff;
    }
    ListItem {
        height: 1;
        color: #202522;
        padding: 0 1;
    }
    ListItem.--highlight {
        background: #d8ece6;
        color: #102f2a;
        text-style: bold;
    }
    ListItem.-disabled {
        color: #7a8f89;
    }
    Button {
        margin-right: 1;
        min-width: 16;
    }
    Button:focus {
        text-style: bold;
    }
    #print-progress {
        display: none;
        margin-top: 1;
    }
    #status {
        height: auto;
        color: #1f4d46;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("p", "print_pdf", "Print"),
        Binding("v", "validate", "Validate"),
        Binding("space", "activate_focused", "Toggle"),
        Binding("enter", "activate_focused", "Select"),
        Binding("u", "move_section_earlier", "Move Earlier"),
        Binding("n", "move_section_later", "Move Later"),
        Binding("tab", "switch_panel", "Switch"),
        Binding("s", "focus_sections", "Sections"),
        Binding("t", "focus_templates", "Templates"),
        Binding("o", "focus_output", "Output"),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up"),
        Binding("j", "move_down", "Down"),
        Binding("q", "quit_without_render", "Quit"),
    ]

    def __init__(
        self,
        yaml_path: Path,
        *,
        template_name: str | None = None,
        output_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.yaml_path = yaml_path
        self.template_name = template_name
        self.output_path = output_path or output_pdf_path(yaml_path)
        loaded = load_material(yaml_path)
        if loaded.document_type != "resume" or not isinstance(loaded.model, ResumeYAML):
            raise ValueError("The interactive TUI currently supports resume YAML files.")
        self.resume = loaded.model
        self.template_names = list_template_names(yaml_path, loaded.document_type)
        inferred_template = template_name or infer_template_name(yaml_path, loaded)
        if inferred_template not in self.template_names:
            self.template_names.append(inferred_template)
            self.template_names.sort()
        self.selected_template_name = inferred_template
        self.template_item_ids = {
            template_name: f"template-{index}"
            for index, template_name in enumerate(self.template_names)
        }
        self.selected_sections = {
            section_name
            for section_name in RESUME_SECTION_DEFAULTS
            if self._section_enabled(section_name) and self._section_has_content(section_name)
        }
        self.section_order = list(RESUME_SECTION_DEFAULTS)
        self.last_printed_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Vertical(
            Label(str(self.yaml_path), id="path"),
            Horizontal(
                Vertical(
                    Label("Resume Sections", id="section-title"),
                    ListView(
                        *[
                            ListItem(
                                Label(self._section_label(section_name), markup=False),
                                id=f"section-{section_name}",
                                disabled=not self._section_has_content(section_name),
                            )
                            for section_name in self.section_order
                        ],
                        id="section-list",
                    ),
                    Label("Templates", id="template-title"),
                    ListView(
                        *[
                            ListItem(
                                Label(self._template_label(template), markup=False),
                                id=self.template_item_ids[template],
                            )
                            for template in self.template_names
                        ],
                        id="template-list",
                    ),
                    Label("Output File", id="output-title"),
                    Input(str(self.output_path), id="output-path"),
                    id="sections",
                ),
                Static(id="details"),
                id="body",
            ),
            Horizontal(
                Button("Print PDF", variant="primary", id="print"),
                Button("Validate", id="validate"),
                Button("Quit", id="quit"),
                id="actions",
            ),
            ProgressBar(total=100, show_eta=False, id="print-progress"),
            Static("", id="status"),
            id="root",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "jobctl resume renderer"
        self.query_one("#section-list", ListView).focus()
        self._refresh_section_labels()
        self._refresh_template_labels()
        self._refresh_details()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id in {"section-list", "template-list"}:
            self._refresh_details()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "section-list":
            self.action_toggle_section()
        elif event.list_view.id == "template-list":
            self.action_select_template()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "output-path":
            self._refresh_details()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "output-path":
            self.action_print_pdf()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "print":
            self.action_print_pdf()
        elif event.button.id == "validate":
            self.action_validate()
        elif event.button.id == "quit":
            self.action_quit_without_render()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "print-pdf":
            return
        progress = self.query_one("#print-progress", ProgressBar)
        status = self.query_one("#status", Static)
        if event.state == WorkerState.SUCCESS:
            progress.update(progress=100)
            status.update(f"Printed {self.output_path}")
            self.last_printed_path = self.output_path
            self._refresh_details()
        elif event.state == WorkerState.ERROR:
            progress.display = False
            status.update("Print failed.")
            error = event.worker.error
            self.query_one("#details", Static).update(
                f"{self._details_text()}\n\nPrint error\n{error}"
            )

    def action_move_up(self) -> None:
        self._move_highlight(-1)

    def action_move_down(self) -> None:
        self._move_highlight(1)

    def action_activate_focused(self) -> None:
        focused = self.focused
        if isinstance(focused, ListView) and focused.id == "template-list":
            self.action_select_template()
        elif isinstance(focused, ListView) and focused.id == "section-list":
            self.action_toggle_section()

    def action_move_section_earlier(self) -> None:
        self._move_section_order(-1)

    def action_move_section_later(self) -> None:
        self._move_section_order(1)

    def action_focus_sections(self) -> None:
        self.query_one("#section-list", ListView).focus()

    def action_focus_templates(self) -> None:
        self.query_one("#template-list", ListView).focus()

    def action_focus_output(self) -> None:
        self.query_one("#output-path", Input).focus()

    def action_toggle_section(self) -> None:
        section_name = self._highlighted_section_name()
        if section_name is None or not self._section_has_content(section_name):
            return
        if section_name in self.selected_sections:
            self.selected_sections.remove(section_name)
        else:
            self.selected_sections.add(section_name)
        self._refresh_section_labels()
        self._refresh_details()

    def action_select_template(self) -> None:
        template_name = self._highlighted_template_name()
        if template_name is None:
            return
        self.selected_template_name = template_name
        self._refresh_template_labels()
        self._refresh_details()

    def action_switch_panel(self) -> None:
        focused = self.focused
        if focused and focused.id == "section-list":
            self.query_one("#template-list", ListView).focus()
        elif focused and focused.id == "template-list":
            self.query_one("#output-path", Input).focus()
        else:
            self.query_one("#section-list", ListView).focus()

    def _move_section_order(self, direction: int) -> None:
        section_name = self._highlighted_section_name()
        if section_name is None:
            return
        current_index = self.section_order.index(section_name)
        next_index = current_index + direction
        if next_index < 0 or next_index >= len(self.section_order):
            return
        self.section_order[current_index], self.section_order[next_index] = (
            self.section_order[next_index],
            self.section_order[current_index],
        )
        section_list = self.query_one("#section-list", ListView)
        item = section_list.children[current_index]
        if direction < 0:
            section_list.move_child(item, before=next_index)
        else:
            section_list.move_child(item, after=next_index)
        section_list.index = next_index
        self._refresh_section_labels()
        section_list.focus()
        self._refresh_details()

    def _move_highlight(self, direction: int) -> None:
        active_list = self.focused if isinstance(self.focused, ListView) else None
        if active_list is None:
            active_list = self.query_one("#section-list", ListView)
            active_list.focus()
        items = list(active_list.children)
        if not items:
            return
        current_index = active_list.index or 0
        for offset in range(1, len(items) + 1):
            next_index = (current_index + direction * offset) % len(items)
            item = items[next_index]
            if isinstance(item, ListItem) and not item.disabled:
                active_list.index = next_index
                return

    def _highlighted_section_name(self) -> str | None:
        section_list = self.query_one("#section-list", ListView)
        item = section_list.highlighted_child
        if item is None or item.id is None or not item.id.startswith("section-"):
            return None
        return item.id.removeprefix("section-")

    def _highlighted_template_name(self) -> str | None:
        template_list = self.query_one("#template-list", ListView)
        item = template_list.highlighted_child
        if item is None or item.id is None:
            return None
        for template_name, item_id in self.template_item_ids.items():
            if item_id == item.id:
                return template_name
        return None

    def _refresh_section_labels(self) -> None:
        for section_name in self.section_order:
            item = self.query_one(f"#section-{section_name}", ListItem)
            item.query_one(Label).update(self._section_label(section_name))

    def _refresh_template_labels(self) -> None:
        for template_name in self.template_names:
            item = self.query_one(f"#{self.template_item_ids[template_name]}", ListItem)
            item.query_one(Label).update(self._template_label(template_name))

    def _section_label(self, section_name: str) -> str:
        title, _ = RESUME_SECTION_DEFAULTS[section_name]
        if not self._section_has_content(section_name):
            return f"[ ] {title} (empty)"
        marker = "x" if section_name in self.selected_sections else " "
        return f"[{marker}] {title}"

    def _template_label(self, template_name: str) -> str:
        marker = "x" if template_name == self.selected_template_name else " "
        return f"({marker}) {template_name}"

    def action_print_pdf(self) -> None:
        enabled, disabled = self._section_overrides()
        output_path = self._current_output_path()
        if output_path is None:
            self.query_one("#status", Static).update("Enter an output PDF path before printing.")
            self.query_one("#output-path", Input).focus()
            return
        self.output_path = output_path
        progress = self.query_one("#print-progress", ProgressBar)
        status = self.query_one("#status", Static)
        progress.display = True
        progress.update(progress=15)
        status.update("Printing PDF...")

        def print_pdf() -> Path:
            render_pdf(
                self.yaml_path,
                self.selected_template_name,
                output_path,
                enable_sections=enabled,
                disable_sections=disabled,
                section_order=self.section_order,
            )
            return output_path

        progress.update(progress=45)
        self.run_worker(
            print_pdf,
            name="print-pdf",
            exit_on_error=False,
            exclusive=True,
            thread=True,
        )

    def action_validate(self) -> None:
        enabled, disabled = self._section_overrides()
        diagnostics = validate_material(
            self.yaml_path,
            enable_sections=enabled,
            disable_sections=disabled,
            section_order=self.section_order,
        )
        detail = self._details_text()
        if diagnostics:
            detail += "\n\nWarnings:\n" + "\n".join(f"- {diagnostic}" for diagnostic in diagnostics)
        else:
            detail += "\n\nValidation passed."
        self.query_one("#details", Static).update(detail)

    def action_quit_without_render(self) -> None:
        self.exit(MaterialRenderResult(output_path=None, rendered=False))

    def _refresh_details(self) -> None:
        self.query_one("#details", Static).update(self._details_text())

    def _details_text(self) -> str:
        selected = []
        skipped = []
        context = build_resume_context(
            self.resume,
            enable_sections=self._selected_sections(),
            disable_sections=self._unselected_sections(),
            section_order=self.section_order,
        )
        rendered_sections = {section["name"] for section in context["sections"]}
        for section_name in self.section_order:
            title = RESUME_SECTION_DEFAULTS[section_name][0]
            has_content = self._section_has_content(section_name)
            if section_name in rendered_sections:
                selected.append(f"- {title}")
            elif has_content:
                skipped.append(f"- {title}")

        selected_text = "\n".join(selected) or "- None"
        skipped_text = "\n".join(skipped) or "- None"
        return (
            "Review the sections that will appear in the PDF.\n\n"
            "Keys\n"
            "- Up/Down or k/j moves through sections\n"
            "- Enter toggles or selects the focused item\n"
            "- u moves the highlighted section earlier; n moves it later\n"
            "- s focuses sections, t focuses templates, o edits output\n"
            "- Tab cycles sections, templates, and output\n"
            "- p prints the PDF\n"
            "- v validates the current selection\n"
            "- q quits without rendering\n\n"
            f"Output\n{self._current_output_display()}\n\n"
            f"Template\n{self.selected_template_name}\n\n"
            f"Printed\n{self.last_printed_path or 'Not yet'}\n\n"
            f"Included\n{selected_text}\n\n"
            f"Available but skipped\n{skipped_text}"
        )

    def _section_overrides(self) -> tuple[set[str], set[str]]:
        return self._selected_sections(), self._unselected_sections()

    def _selected_sections(self) -> set[str]:
        return set(self.selected_sections)

    def _unselected_sections(self) -> set[str]:
        return set(RESUME_SECTION_DEFAULTS) - self.selected_sections

    def _current_output_path(self) -> Path | None:
        raw_value = self.query_one("#output-path", Input).value.strip()
        if not raw_value:
            return None
        return Path(raw_value).expanduser()

    def _current_output_display(self) -> str:
        return str(self._current_output_path() or "(not set)")

    def _section_enabled(self, section_name: str) -> bool:
        config = self.resume.render.sections.get(section_name) if self.resume.render else None
        return config.enabled if config else True

    def _section_has_content(self, section_name: str) -> bool:
        value = self.resume.model_dump(mode="json").get(section_name)
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, dict | list | tuple | set):
            return bool(value)
        return True


def run_material_render_tui(
    yaml_path: Path,
    *,
    template_name: str | None = None,
    output_path: Path | None = None,
) -> MaterialRenderResult:
    """Run the material renderer TUI and return the render result."""
    result = MaterialRenderApp(
        yaml_path,
        template_name=template_name,
        output_path=output_path,
    ).run()
    if result is None:
        return MaterialRenderResult(output_path=None, rendered=False)
    return result
