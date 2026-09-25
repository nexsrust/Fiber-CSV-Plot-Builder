from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"

PLOT_TYPES = {
    "曲线 (Line)": "l",
    "散点 (Scatter)": "s",
    "曲线+点 (Line + Symbol)": "y",
    "柱状图 (Column)": "c",
}

COLOR_CYCLE = [
    "#35AD6B",  # reference green
    "#3478BF",
    "#E76F51",
    "#8E5DB7",
    "#E9A23B",
    "#2A9D8F",
    "#D1495B",
    "#6C757D",
]

CHINESE_HELP = """Fiber CSV Plot Builder 中文使用说明

一、导入 CSV 数据
1. 打开“1 导入数据”页面，点击“浏览…”选择包含 CSV 的文件夹。
2. 如 CSV 位于下级文件夹，勾选“包含子文件夹”，再点击“扫描 CSV”。
3. 在左侧选择文件：双击文件行，或点击“切换导入状态”。“✓”表示会导入。
4. 单击某个 CSV，在右侧选择该文件需要导入的数据列。
   - 按住 Ctrl 可逐个选择；按住 Shift 可连续选择。
   - “全选列”和“清空列”只影响当前 CSV。
   - “AAPlot 常用列”会选择时间列、mean、SEM、dF/F、z-score 等常用列。
5. 点击“导入所选数据到 Origin”。每个 CSV 会建立一个 Origin 工作簿，且只包含选中的列。

二、安排作图数据
1. 打开“2 作图设置”页面。
2. 依次指定：数据来源、X 轴列、Y 轴列、Y Error 列和图形类型。
3. 如果不需要误差线，将 Y Error 设为“(无)”。
4. 点击“选择颜色…”为当前组设置独立颜色，并填写图例名称。
5. 点击“添加到作图列表”。可以继续加入任意数量的数据组。
6. 作图列表中的顺序就是曲线叠放和图例顺序；可用“上移”“下移”调整。
7. 双击列表中的项目可载入设置，修改后点击“更新选中项”。

三、AAPlot 快捷预设
1. 选择 event_aligned_average.csv。
2. 确保已选择 relative_time_s，以及需要的 mean / SEM 列。
3. 点击“AAPlot dF/F 预设（410 / 470 / Ratio）”。
4. 应用会自动添加以下曲线：
   - 410_dff_percent_mean，误差为 410_dff_percent_sem；
   - 470_dff_percent_mean，误差为 470_dff_percent_sem；
   - ratio_470_410_dff_percent_mean，误差为对应 SEM。
5. 不需要的曲线可以删除；每条曲线的颜色、图例和图形类型都可以修改。

四、创建图形
1. 设置图页名称、X 轴标题、Y 轴标题和线宽。
2. 点击“在 Origin 中创建图形”。
3. 图形生成后仍可使用 Origin 的 Plot Details、坐标轴和图例工具继续修改。

支持的图形类型
- 曲线（Line）
- 散点（Scatter）
- 曲线+点（Line + Symbol）
- 柱状图（Column）

注意事项
- X、Y 和 Y Error 必须来自同一个 CSV 工作表。
- 只有被选中导入的数据列才能用于作图。
- 如果修改了某个 CSV 的选中列，请重新点击“导入所选数据到 Origin”。
- SEM/SD 列不需要手动设置为 Origin 的 E 列；应用会根据 Y Error 选项自动创建误差线。
"""


@dataclass
class CsvSource:
    path: Path
    headers: List[str]
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    included: bool = False
    selected_headers: Set[str] = field(default_factory=set)
    imported_worksheet: object = None
    imported_columns: Dict[str, int] = field(default_factory=dict)
    imported_signature: Tuple[str, ...] = field(default_factory=tuple)


@dataclass
class SeriesPlan:
    source_path: Path
    x: str
    y: str
    yerr: str
    plot_type_label: str
    color: str
    legend: str


def _load_settings() -> Dict[str, str]:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(values: Dict[str, str]) -> None:
    try:
        SETTINGS_FILE.write_text(
            json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def inspect_csv(path: Path) -> CsvSource:
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                sample = handle.read(8192)
                handle.seek(0)
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
                except csv.Error:
                    delimiter = ","
                row = next(csv.reader(handle, delimiter=delimiter), [])
                headers = [str(value).strip() or "Column_{}".format(i + 1) for i, value in enumerate(row)]
                if not headers:
                    raise ValueError("CSV 没有表头")
                return CsvSource(
                    path=path,
                    headers=headers,
                    delimiter=delimiter,
                    encoding=encoding,
                    selected_headers=set(headers),
                )
        except Exception as exc:
            last_error = exc
    raise ValueError("无法读取 {}: {}".format(path.name, last_error))


def scan_csv_files(folder: Path, recursive: bool = False) -> Tuple[List[CsvSource], List[str]]:
    pattern = "**/*.csv" if recursive else "*.csv"
    sources: List[CsvSource] = []
    errors: List[str] = []
    for path in sorted(folder.glob(pattern), key=lambda item: str(item).lower()):
        try:
            sources.append(inspect_csv(path))
        except Exception as exc:
            errors.append(str(exc))
    return sources, errors


def _coerce_column(values: Sequence[str]) -> List[object]:
    nonempty = [value.strip() for value in values if value.strip()]
    if not nonempty:
        return [float("nan") for _ in values]

    numeric_count = 0
    for value in nonempty:
        try:
            float(value)
            numeric_count += 1
        except ValueError:
            pass

    if numeric_count == len(nonempty):
        result: List[object] = []
        for value in values:
            value = value.strip()
            if not value:
                result.append(float("nan"))
            else:
                try:
                    result.append(float(value))
                except ValueError:
                    result.append(float("nan"))
        return result
    return [value.strip() for value in values]


def read_csv_columns(source: CsvSource, selected: Sequence[str]) -> Dict[str, List[object]]:
    selected_set = set(selected)
    indices = [index for index, header in enumerate(source.headers) if header in selected_set]
    if not indices:
        raise ValueError("{} 没有选择数据列".format(source.path.name))

    raw: Dict[str, List[str]] = {source.headers[index]: [] for index in indices}
    with source.path.open("r", encoding=source.encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=source.delimiter)
        next(reader, None)
        for row in reader:
            for index in indices:
                raw[source.headers[index]].append(row[index] if index < len(row) else "")
    return {header: _coerce_column(values) for header, values in raw.items()}


def import_source_to_origin(source: CsvSource, selected: Optional[Sequence[str]] = None):
    import originpro as op

    chosen = list(selected or [h for h in source.headers if h in source.selected_headers])
    chosen = [header for header in source.headers if header in set(chosen)]
    signature = tuple(chosen)
    if source.imported_worksheet is not None and source.imported_signature == signature:
        return source.imported_worksheet, source.imported_columns

    data = read_csv_columns(source, chosen)
    book = op.new_book("w", lname=source.path.stem)
    sheet = book[0]
    sheet.name = "Data"
    sheet.cols = len(chosen)

    column_map: Dict[str, int] = {}
    for index, header in enumerate(chosen):
        axis = "X" if header in ("relative_time_s", "original_time_s", "original_time_min") else ""
        sheet.from_list(index, data[header], lname=header, axis=axis)
        sheet.set_label(index, str(source.path), "Source")
        column_map[header] = index

    source.imported_worksheet = sheet
    source.imported_columns = column_map
    source.imported_signature = signature
    return sheet, column_map


def create_origin_graph(
    plans: Sequence[SeriesPlan],
    source_by_path: Dict[Path, CsvSource],
    title: str,
    x_title: str,
    y_title: str,
    line_width: float = 3.0,
):
    import originpro as op

    graph = op.new_graph(lname=title or "Fiber CSV Plot")
    layer = graph[0]

    for plan in plans:
        source = source_by_path[plan.source_path]
        required = [plan.x, plan.y]
        if plan.yerr:
            required.append(plan.yerr)
        selected = [header for header in source.headers if header in source.selected_headers]
        missing = [header for header in required if header not in selected]
        if missing:
            raise ValueError(
                "{} 中这些作图列没有被选中: {}".format(source.path.name, ", ".join(missing))
            )
        sheet, column_map = import_source_to_origin(source, selected)
        kwargs = {
            "coly": column_map[plan.y],
            "colx": column_map[plan.x],
            "type": PLOT_TYPES[plan.plot_type_label],
        }
        if plan.yerr:
            kwargs["colyerr"] = column_map[plan.yerr]
        plot = layer.add_plot(sheet, **kwargs)
        if plot is None:
            raise RuntimeError("Origin 无法添加曲线: {}".format(plan.legend or plan.y))
        plot.color = plan.color
        try:
            plot.layer.SetNumProp(
                "plot{}.line.width".format(plot.index() + 1), float(line_width)
            )
        except Exception:
            pass
        if PLOT_TYPES[plan.plot_type_label] in ("s", "y"):
            try:
                plot.symbol_size = 8
                plot.symbol_interior = 1
            except Exception:
                pass
        if plan.legend and plan.legend != plan.y:
            try:
                sheet.set_label(column_map[plan.y], plan.legend, "L")
            except Exception:
                pass

    layer.axis("x").title = x_title
    layer.axis("y").title = y_title
    layer.rescale()
    try:
        layer.lt_exec("legend -r;")
    except Exception:
        pass
    try:
        graph.activate()
    except Exception:
        pass
    return graph


class FiberCsvPlotApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Fiber CSV Plot Builder — Origin 数据导入与作图")
        self.root.geometry("1180x790")
        self.root.minsize(1020, 680)

        self.sources: List[CsvSource] = []
        self.source_by_iid: Dict[str, CsvSource] = {}
        self.plans: List[SeriesPlan] = []
        self._loading_columns = False
        self.current_color = COLOR_CYCLE[0]
        self.current_column_source: Optional[CsvSource] = None

        self.folder_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="请选择包含 CSV 的文件夹。")
        self.plot_source_var = tk.StringVar()
        self.x_var = tk.StringVar()
        self.y_var = tk.StringVar()
        self.err_var = tk.StringVar(value="(无)")
        self.plot_type_var = tk.StringVar(value="曲线 (Line)")
        self.legend_var = tk.StringVar()
        self.graph_title_var = tk.StringVar(value="Event-aligned fluorescence")
        self.x_title_var = tk.StringVar(value="Time (s)")
        self.y_title_var = tk.StringVar(value="ΔF/F₀ (%)")
        self.line_width_var = tk.DoubleVar(value=3.0)

        self._build_ui()
        settings = _load_settings()
        initial = settings.get("last_folder", "")
        if initial and Path(initial).is_dir():
            self.folder_var.set(initial)
            self.root.after(80, self.scan_folder)

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        top = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Fiber CSV Plot Builder", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, text="选择数据 → 安排曲线 → 在 Origin 中作图", foreground="#555555").pack(side="left", padx=16)
        ttk.Button(top, text="中文使用说明", command=self.show_chinese_help).pack(side="right")

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(4, 6))
        self.import_tab = ttk.Frame(self.tabs, padding=10)
        self.plot_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.import_tab, text="1  导入数据")
        self.tabs.add(self.plot_tab, text="2  作图设置")
        self._build_import_tab()
        self._build_plot_tab()

        status = ttk.Frame(self.root, padding=(12, 4, 12, 10))
        status.pack(fill="x")
        ttk.Separator(status).pack(fill="x", pady=(0, 6))
        ttk.Label(status, textvariable=self.status_var, foreground="#275D38").pack(anchor="w")

    def show_chinese_help(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Fiber CSV Plot Builder — 中文使用说明")
        window.geometry("820x680")
        window.minsize(680, 500)
        window.transient(self.root)

        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        text = tk.Text(
            frame,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            padx=12,
            pady=12,
            spacing1=2,
            spacing3=5,
        )
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.insert("1.0", CHINESE_HELP)
        text.configure(state="disabled")

        buttons = ttk.Frame(window, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="关闭", command=window.destroy).pack(side="right")
        window.bind("<Escape>", lambda _event: window.destroy())
        window.focus_set()

    def _build_import_tab(self) -> None:
        folder = ttk.LabelFrame(self.import_tab, text="CSV 文件夹", padding=10)
        folder.pack(fill="x", pady=(0, 10))
        ttk.Entry(folder, textvariable=self.folder_var).pack(side="left", fill="x", expand=True)
        ttk.Button(folder, text="浏览…", command=self.choose_folder).pack(side="left", padx=(8, 4))
        ttk.Button(folder, text="扫描 CSV", command=self.scan_folder).pack(side="left", padx=4)
        ttk.Checkbutton(folder, text="包含子文件夹", variable=self.recursive_var).pack(side="left", padx=(10, 0))

        body = ttk.Panedwindow(self.import_tab, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.LabelFrame(body, text="① 选择要导入的 CSV", padding=8)
        right = ttk.LabelFrame(body, text="② 选择当前 CSV 中的数据列", padding=8)
        body.add(left, weight=3)
        body.add(right, weight=2)

        self.file_tree = ttk.Treeview(left, columns=("use", "file", "columns"), show="headings", selectmode="browse")
        self.file_tree.heading("use", text="导入")
        self.file_tree.heading("file", text="CSV 文件")
        self.file_tree.heading("columns", text="已选列")
        self.file_tree.column("use", width=55, anchor="center", stretch=False)
        self.file_tree.column("file", width=430)
        self.file_tree.column("columns", width=80, anchor="center", stretch=False)
        file_scroll = ttk.Scrollbar(left, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=file_scroll.set)
        self.file_tree.pack(side="left", fill="both", expand=True)
        file_scroll.pack(side="right", fill="y")
        self.file_tree.bind("<<TreeviewSelect>>", self.on_file_focus)
        self.file_tree.bind("<Double-1>", self.toggle_focused_file)

        file_buttons = ttk.Frame(left)
        file_buttons.pack(fill="x", side="bottom", pady=(8, 0))
        ttk.Button(file_buttons, text="切换导入状态", command=self.toggle_focused_file).pack(side="left")
        ttk.Button(file_buttons, text="全选文件", command=lambda: self.set_all_files(True)).pack(side="left", padx=6)
        ttk.Button(file_buttons, text="清空文件", command=lambda: self.set_all_files(False)).pack(side="left")

        ttk.Label(right, text="可用 Ctrl / Shift 多选；选择会自动保存。", foreground="#555555").pack(anchor="w", pady=(0, 6))
        list_frame = ttk.Frame(right)
        list_frame.pack(fill="both", expand=True)
        self.column_list = tk.Listbox(list_frame, selectmode="extended", exportselection=False, activestyle="dotbox")
        col_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.column_list.yview)
        self.column_list.configure(yscrollcommand=col_scroll.set)
        self.column_list.pack(side="left", fill="both", expand=True)
        col_scroll.pack(side="right", fill="y")
        self.column_list.bind("<<ListboxSelect>>", self.on_column_selection)

        col_buttons = ttk.Frame(right)
        col_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(col_buttons, text="全选列", command=lambda: self.set_all_columns(True)).pack(side="left")
        ttk.Button(col_buttons, text="清空列", command=lambda: self.set_all_columns(False)).pack(side="left", padx=6)
        ttk.Button(col_buttons, text="AAPlot 常用列", command=self.select_aaplot_columns).pack(side="left")

        bottom = ttk.Frame(self.import_tab)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="导入所选数据到 Origin", style="Accent.TButton", command=self.import_selected).pack(side="right")

    def _build_plot_tab(self) -> None:
        editor = ttk.LabelFrame(self.plot_tab, text="③ 添加一组作图数据", padding=10)
        editor.pack(fill="x", pady=(0, 10))

        labels = ["数据来源", "X 轴", "Y 轴", "Y Error", "图形类型", "图例名称"]
        for index, text in enumerate(labels):
            ttk.Label(editor, text=text).grid(row=0, column=index, sticky="w", padx=(0, 6))
        self.source_combo = ttk.Combobox(editor, textvariable=self.plot_source_var, state="readonly", width=24)
        self.x_combo = ttk.Combobox(editor, textvariable=self.x_var, state="readonly", width=19)
        self.y_combo = ttk.Combobox(editor, textvariable=self.y_var, state="readonly", width=24)
        self.err_combo = ttk.Combobox(editor, textvariable=self.err_var, state="readonly", width=22)
        self.type_combo = ttk.Combobox(editor, textvariable=self.plot_type_var, values=list(PLOT_TYPES), state="readonly", width=20)
        self.legend_entry = ttk.Entry(editor, textvariable=self.legend_var, width=21)
        widgets = [self.source_combo, self.x_combo, self.y_combo, self.err_combo, self.type_combo, self.legend_entry]
        for index, widget in enumerate(widgets):
            widget.grid(row=1, column=index, sticky="ew", padx=(0, 6), pady=(2, 8))
            editor.columnconfigure(index, weight=1 if index in (0, 2) else 0)
        self.source_combo.bind("<<ComboboxSelected>>", self.on_plot_source_changed)
        self.y_combo.bind("<<ComboboxSelected>>", self.on_y_changed)

        color_row = ttk.Frame(editor)
        color_row.grid(row=2, column=0, columnspan=6, sticky="ew")
        ttk.Label(color_row, text="曲线颜色:").pack(side="left")
        self.color_chip = tk.Label(color_row, text="      ", bg=self.current_color, relief="solid", bd=1)
        self.color_chip.pack(side="left", padx=6)
        ttk.Button(color_row, text="选择颜色…", command=self.choose_color).pack(side="left")
        ttk.Button(color_row, text="添加到作图列表", style="Accent.TButton", command=self.add_plan).pack(side="right")
        ttk.Button(color_row, text="更新选中项", command=self.update_selected_plan).pack(side="right", padx=6)
        ttk.Button(color_row, text="AAPlot dF/F 预设（410 / 470 / Ratio）", command=self.add_aaplot_preset).pack(side="right", padx=6)

        middle = ttk.LabelFrame(self.plot_tab, text="④ 作图列表（顺序即绘图与图例顺序）", padding=8)
        middle.pack(fill="both", expand=True)
        columns = ("order", "file", "x", "y", "err", "type", "color", "legend")
        self.plan_tree = ttk.Treeview(middle, columns=columns, show="headings", selectmode="browse", height=12)
        headings = {
            "order": "#", "file": "CSV", "x": "X", "y": "Y", "err": "Y Error",
            "type": "图形", "color": "颜色", "legend": "图例",
        }
        widths = {"order": 35, "file": 150, "x": 130, "y": 190, "err": 170, "type": 105, "color": 78, "legend": 150}
        for name in columns:
            self.plan_tree.heading(name, text=headings[name])
            self.plan_tree.column(name, width=widths[name], anchor="center" if name in ("order", "color") else "w")
        plan_scroll = ttk.Scrollbar(middle, orient="vertical", command=self.plan_tree.yview)
        self.plan_tree.configure(yscrollcommand=plan_scroll.set)
        self.plan_tree.pack(side="left", fill="both", expand=True)
        plan_scroll.pack(side="right", fill="y")
        self.plan_tree.bind("<Double-1>", self.load_selected_plan)

        plan_buttons = ttk.Frame(self.plot_tab)
        plan_buttons.pack(fill="x", pady=(7, 10))
        ttk.Button(plan_buttons, text="上移", command=lambda: self.move_plan(-1)).pack(side="left")
        ttk.Button(plan_buttons, text="下移", command=lambda: self.move_plan(1)).pack(side="left", padx=5)
        ttk.Button(plan_buttons, text="删除选中", command=self.remove_plan).pack(side="left")
        ttk.Button(plan_buttons, text="清空列表", command=self.clear_plans).pack(side="left", padx=5)

        graph = ttk.LabelFrame(self.plot_tab, text="⑤ 图形设置", padding=10)
        graph.pack(fill="x")
        for col, text in enumerate(("图页名称", "X 轴标题", "Y 轴标题", "线宽")):
            ttk.Label(graph, text=text).grid(row=0, column=col, sticky="w", padx=(0, 8))
        ttk.Entry(graph, textvariable=self.graph_title_var, width=28).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Entry(graph, textvariable=self.x_title_var, width=22).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Entry(graph, textvariable=self.y_title_var, width=22).grid(row=1, column=2, sticky="ew", padx=(0, 8))
        ttk.Spinbox(graph, from_=0.5, to=10.0, increment=0.5, textvariable=self.line_width_var, width=8).grid(row=1, column=3, sticky="w")
        ttk.Button(graph, text="在 Origin 中创建图形", style="Accent.TButton", command=self.create_graph).grid(row=1, column=4, padx=(18, 0), sticky="e")
        graph.columnconfigure(0, weight=1)
        graph.columnconfigure(1, weight=1)
        graph.columnconfigure(2, weight=1)

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or None, title="选择包含 CSV 的文件夹")
        if chosen:
            self.folder_var.set(chosen)
            self.scan_folder()

    def scan_folder(self) -> None:
        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir():
            messagebox.showwarning("文件夹无效", "请选择一个有效的 CSV 文件夹。")
            return
        self.status_var.set("正在扫描 CSV…")
        self.root.update_idletasks()
        sources, errors = scan_csv_files(folder, self.recursive_var.get())
        self.sources = sources
        self.source_by_iid.clear()
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        for index, source in enumerate(sources):
            if source.path.name.lower() == "event_aligned_average.csv":
                source.included = True
            iid = "source{}".format(index)
            self.source_by_iid[iid] = source
            self.file_tree.insert("", "end", iid=iid, values=("✓" if source.included else "", source.path.name, len(source.selected_headers)))
        if sources:
            first_iid = next((iid for iid, src in self.source_by_iid.items() if src.included), "source0")
            self.file_tree.selection_set(first_iid)
            self.file_tree.focus(first_iid)
            self.on_file_focus()
        _save_settings({"last_folder": str(folder)})
        self.refresh_plot_sources()
        text = "找到 {} 个 CSV。".format(len(sources))
        if errors:
            text += " 另有 {} 个文件无法读取。".format(len(errors))
        self.status_var.set(text)

    def on_file_focus(self, _event=None) -> None:
        selected = self.file_tree.selection()
        if not selected:
            return
        source = self.source_by_iid[selected[0]]
        self.current_column_source = source
        self._loading_columns = True
        self.column_list.delete(0, "end")
        for index, header in enumerate(source.headers):
            self.column_list.insert("end", header)
            if header in source.selected_headers:
                self.column_list.selection_set(index)
        self._loading_columns = False

    def toggle_focused_file(self, _event=None) -> None:
        selected = self.file_tree.selection()
        if not selected:
            return
        iid = selected[0]
        source = self.source_by_iid[iid]
        source.included = not source.included
        self._refresh_source_row(iid, source)
        self.refresh_plot_sources()

    def set_all_files(self, included: bool) -> None:
        for iid, source in self.source_by_iid.items():
            source.included = included
            self._refresh_source_row(iid, source)
        self.refresh_plot_sources()

    def _refresh_source_row(self, iid: str, source: CsvSource) -> None:
        marker = "✓" if source.included else ""
        if source.imported_worksheet is not None:
            marker = "✓ 已导入" if source.included else "已导入"
        self.file_tree.item(iid, values=(marker, source.path.name, len(source.selected_headers)))

    def on_column_selection(self, _event=None) -> None:
        if self._loading_columns or self.current_column_source is None:
            return
        indices = self.column_list.curselection()
        self.current_column_source.selected_headers = {self.current_column_source.headers[index] for index in indices}
        iid = next((key for key, value in self.source_by_iid.items() if value is self.current_column_source), "")
        if iid:
            self._refresh_source_row(iid, self.current_column_source)
        self.refresh_plot_sources()

    def set_all_columns(self, selected: bool) -> None:
        if self.current_column_source is None:
            return
        self._loading_columns = True
        self.column_list.selection_clear(0, "end")
        if selected:
            self.column_list.selection_set(0, "end")
            self.current_column_source.selected_headers = set(self.current_column_source.headers)
        else:
            self.current_column_source.selected_headers.clear()
        self._loading_columns = False
        self.on_column_selection()
        iid = next((key for key, value in self.source_by_iid.items() if value is self.current_column_source), "")
        if iid:
            self._refresh_source_row(iid, self.current_column_source)
        self.refresh_plot_sources()

    def select_aaplot_columns(self) -> None:
        source = self.current_column_source
        if source is None:
            return
        preferred = {
            header for header in source.headers
            if header in ("relative_time_s", "original_time_s", "original_time_min", "marker_name", "source_event_index")
            or header.endswith(("_mean", "_sem"))
            or header in ("dff_percent", "zscore", "analysis_trace")
        }
        source.selected_headers = preferred or set(source.headers)
        self.on_file_focus()
        iid = next((key for key, value in self.source_by_iid.items() if value is source), "")
        if iid:
            self._refresh_source_row(iid, source)
        self.refresh_plot_sources()

    def import_selected(self) -> None:
        selected = [source for source in self.sources if source.included]
        if not selected:
            messagebox.showwarning("没有选择文件", "请先勾选至少一个 CSV 文件。")
            return
        try:
            for position, source in enumerate(selected, 1):
                if not source.selected_headers:
                    raise ValueError("{} 没有选择数据列".format(source.path.name))
                self.status_var.set("正在导入 {}/{}: {}".format(position, len(selected), source.path.name))
                self.root.update_idletasks()
                import_source_to_origin(source)
                iid = next((key for key, value in self.source_by_iid.items() if value is source), "")
                if iid:
                    self._refresh_source_row(iid, source)
            self.status_var.set("已将 {} 个 CSV 的所选列导入 Origin。".format(len(selected)))
            messagebox.showinfo("导入完成", "所选 CSV 和数据列已导入 Origin 工作簿。")
            self.tabs.select(self.plot_tab)
            self.refresh_plot_sources()
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            self.status_var.set("导入失败: {}".format(exc))

    def included_sources(self) -> List[CsvSource]:
        return [source for source in self.sources if source.included and source.selected_headers]

    def source_label(self, source: CsvSource) -> str:
        duplicates = sum(1 for item in self.sources if item.path.name == source.path.name)
        return str(source.path) if duplicates > 1 else source.path.name

    def source_for_label(self, label: str) -> Optional[CsvSource]:
        for source in self.included_sources():
            if self.source_label(source) == label:
                return source
        return None

    def refresh_plot_sources(self) -> None:
        labels = [self.source_label(source) for source in self.included_sources()]
        current = self.plot_source_var.get()
        self.source_combo["values"] = labels
        if current not in labels:
            self.plot_source_var.set(labels[0] if labels else "")
        self.on_plot_source_changed()

    def on_plot_source_changed(self, _event=None) -> None:
        source = self.source_for_label(self.plot_source_var.get())
        headers = [header for header in source.headers if header in source.selected_headers] if source else []
        self.x_combo["values"] = headers
        self.y_combo["values"] = headers
        self.err_combo["values"] = ["(无)"] + headers
        if not headers:
            self.x_var.set("")
            self.y_var.set("")
            self.err_var.set("(无)")
            return
        x_default = next((name for name in ("relative_time_s", "original_time_s", "original_time_min") if name in headers), headers[0])
        y_default = next((name for name in headers if name.endswith("_dff_percent_mean")), None)
        if y_default is None:
            y_default = next((name for name in headers if name in ("dff_percent", "zscore", "analysis_trace")), headers[min(1, len(headers) - 1)])
        self.x_var.set(x_default)
        self.y_var.set(y_default)
        self.legend_var.set(y_default)
        self._suggest_error_for_y(source, y_default)

    def on_y_changed(self, _event=None) -> None:
        source = self.source_for_label(self.plot_source_var.get())
        if source:
            self._suggest_error_for_y(source, self.y_var.get())
            self.legend_var.set(self.y_var.get())

    def _suggest_error_for_y(self, source: CsvSource, y_name: str) -> None:
        headers = source.selected_headers
        candidates = []
        if y_name.endswith("_mean"):
            candidates.append(y_name[:-5] + "_sem")
            candidates.append(y_name[:-5] + "_sd")
        candidates.extend([y_name + "_sem", y_name + "_sd"])
        self.err_var.set(next((name for name in candidates if name in headers), "(无)"))

    def choose_color(self) -> None:
        chosen = colorchooser.askcolor(color=self.current_color, title="选择曲线颜色")
        if chosen and chosen[1]:
            self.current_color = chosen[1].upper()
            self.color_chip.configure(bg=self.current_color)

    def _plan_from_editor(self) -> SeriesPlan:
        source = self.source_for_label(self.plot_source_var.get())
        if source is None:
            raise ValueError("请选择数据来源。")
        x_name = self.x_var.get()
        y_name = self.y_var.get()
        if not x_name or not y_name:
            raise ValueError("必须指定 X 轴和 Y 轴数据列。")
        err_name = "" if self.err_var.get() in ("", "(无)") else self.err_var.get()
        return SeriesPlan(
            source_path=source.path,
            x=x_name,
            y=y_name,
            yerr=err_name,
            plot_type_label=self.plot_type_var.get(),
            color=self.current_color,
            legend=self.legend_var.get().strip() or y_name,
        )

    def add_plan(self) -> None:
        try:
            plan = self._plan_from_editor()
            self.plans.append(plan)
            self._refresh_plan_tree(select_index=len(self.plans) - 1)
            self.current_color = COLOR_CYCLE[len(self.plans) % len(COLOR_CYCLE)]
            self.color_chip.configure(bg=self.current_color)
            self.status_var.set("已添加作图数据: {}".format(plan.legend))
        except Exception as exc:
            messagebox.showwarning("无法添加", str(exc))

    def add_aaplot_preset(self) -> None:
        source = self.source_for_label(self.plot_source_var.get())
        if source is None:
            source = next((item for item in self.included_sources() if item.path.name.lower() == "event_aligned_average.csv"), None)
        if source is None:
            messagebox.showwarning("未找到数据", "请先选择 event_aligned_average.csv。")
            return
        x_name = "relative_time_s" if "relative_time_s" in source.selected_headers else ""
        if not x_name:
            messagebox.showwarning("缺少 X 列", "请在该 CSV 中选择 relative_time_s。")
            return
        presets = [
            ("410_dff_percent_mean", "410_dff_percent_sem", "410", "#35AD6B"),
            ("470_dff_percent_mean", "470_dff_percent_sem", "470", "#3478BF"),
            ("ratio_470_410_dff_percent_mean", "ratio_470_410_dff_percent_sem", "470 / 410", "#E76F51"),
        ]
        added = 0
        existing = {(plan.source_path, plan.y) for plan in self.plans}
        for y_name, err_name, legend, color in presets:
            if y_name in source.selected_headers and (source.path, y_name) not in existing:
                self.plans.append(SeriesPlan(
                    source_path=source.path,
                    x=x_name,
                    y=y_name,
                    yerr=err_name if err_name in source.selected_headers else "",
                    plot_type_label="曲线 (Line)",
                    color=color,
                    legend=legend,
                ))
                added += 1
        self._refresh_plan_tree(select_index=len(self.plans) - 1 if self.plans else None)
        self.status_var.set("AAPlot 预设已添加 {} 组曲线；可继续删除、改色或修改列。".format(added))

    def _refresh_plan_tree(self, select_index: Optional[int] = None) -> None:
        for item in self.plan_tree.get_children():
            self.plan_tree.delete(item)
        for index, plan in enumerate(self.plans):
            iid = "plan{}".format(index)
            self.plan_tree.insert("", "end", iid=iid, values=(
                index + 1, plan.source_path.name, plan.x, plan.y, plan.yerr or "—",
                plan.plot_type_label.split(" (")[0], plan.color, plan.legend,
            ))
        if select_index is not None and 0 <= select_index < len(self.plans):
            iid = "plan{}".format(select_index)
            self.plan_tree.selection_set(iid)
            self.plan_tree.focus(iid)
            self.plan_tree.see(iid)

    def selected_plan_index(self) -> Optional[int]:
        selected = self.plan_tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0].replace("plan", ""))
        except ValueError:
            return None

    def load_selected_plan(self, _event=None) -> None:
        index = self.selected_plan_index()
        if index is None:
            return
        plan = self.plans[index]
        source = next((item for item in self.sources if item.path == plan.source_path), None)
        if source is None:
            return
        self.plot_source_var.set(self.source_label(source))
        self.on_plot_source_changed()
        self.x_var.set(plan.x)
        self.y_var.set(plan.y)
        self.err_var.set(plan.yerr or "(无)")
        self.plot_type_var.set(plan.plot_type_label)
        self.legend_var.set(plan.legend)
        self.current_color = plan.color
        self.color_chip.configure(bg=self.current_color)

    def update_selected_plan(self) -> None:
        index = self.selected_plan_index()
        if index is None:
            messagebox.showwarning("未选择", "请先在作图列表中选择一项。")
            return
        try:
            self.plans[index] = self._plan_from_editor()
            self._refresh_plan_tree(select_index=index)
            self.status_var.set("已更新第 {} 组作图数据。".format(index + 1))
        except Exception as exc:
            messagebox.showwarning("无法更新", str(exc))

    def move_plan(self, offset: int) -> None:
        index = self.selected_plan_index()
        if index is None:
            return
        target = index + offset
        if 0 <= target < len(self.plans):
            self.plans[index], self.plans[target] = self.plans[target], self.plans[index]
            self._refresh_plan_tree(select_index=target)

    def remove_plan(self) -> None:
        index = self.selected_plan_index()
        if index is not None:
            self.plans.pop(index)
            self._refresh_plan_tree(select_index=min(index, len(self.plans) - 1) if self.plans else None)

    def clear_plans(self) -> None:
        self.plans.clear()
        self._refresh_plan_tree()

    def create_graph(self) -> None:
        if not self.plans:
            messagebox.showwarning("没有作图数据", "请先添加至少一组 X/Y 数据。")
            return
        try:
            self.status_var.set("正在 Origin 中创建图形…")
            self.root.update_idletasks()
            source_by_path = {source.path: source for source in self.sources}
            create_origin_graph(
                self.plans,
                source_by_path,
                self.graph_title_var.get().strip(),
                self.x_title_var.get().strip(),
                self.y_title_var.get().strip(),
                float(self.line_width_var.get()),
            )
            self.status_var.set("图形已创建，可直接在 Origin 中继续编辑或保存项目。")
            messagebox.showinfo("作图完成", "图形已在 Origin 中创建。\n每组数据已按列表中的颜色、图形类型和误差列绘制。")
        except Exception as exc:
            messagebox.showerror("作图失败", str(exc))
            self.status_var.set("作图失败: {}".format(exc))


_APP_WINDOW = None


def main() -> None:
    global _APP_WINDOW
    if _APP_WINDOW is not None:
        try:
            _APP_WINDOW.deiconify()
            _APP_WINDOW.lift()
            _APP_WINDOW.focus_force()
            return
        except Exception:
            _APP_WINDOW = None
    root = tk.Tk()
    _APP_WINDOW = root
    FiberCsvPlotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
