"""Interfaz principal de Free2Play."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import TclError, filedialog, messagebox
from typing import Any, Callable

import customtkinter as ctk

from app_paths import prepare_user_data_dir, user_data_dir
from api_bridge_auth import find_api_bridge_token
from app_settings import AppSettingsStore
from connections.cli_commands import (
    api_bridge_install_command,
    tiktok_command,
)
from connections.minecraft_api import (
    CommandExecution,
    execute_command_sequence,
    test_connection,
)
from profiles import RuleProfile, RuleProfileStore
from rules_engine import (
    Rule,
    RuleEngine,
    RuleStore,
    missing_event_fields,
    render_action_commands,
    render_tellraw_command,
)


APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
APP_DATA_DIR = user_data_dir()
RULES_PATH = APP_DATA_DIR / "rules.json"
PROFILES_PATH = APP_DATA_DIR / "profiles.json"
EVENT_TYPES = ("comment", "gift", "follow", "share", "like", "join")
EVENT_LABELS = {
    "comment": "Comentario",
    "gift": "Regalo",
    "follow": "Nuevo seguidor",
    "share": "Compartir",
    "like": "Me gusta",
    "join": "Alguien entra",
}
EVENT_TYPES_BY_LABEL = {
    label: event_type for event_type, label in EVENT_LABELS.items()
}
ACTION_PRESETS = {
    "comment": "{text}",
    "gift": "{usuario} envió {gift} x{amount}",
    "follow": "¡Gracias por seguir, {usuario}!",
    "share": "¡Gracias por compartir, {usuario}!",
    "like": "¡Gracias por los likes, {usuario}!",
    "join": "¡Bienvenido, {usuario}!",
}
EVENT_FIELDS = {
    "comment": "text, userid, shortname, user, event_id, timestamp",
    "gift": (
        "gift_name, gift_id, amount, repeat_count, repeat_end, "
        "diamond_count, total_diamond_count, userid, shortname, user"
    ),
    "follow": "userid, shortname, user, event_id, timestamp",
    "share": "userid, shortname, user, event_id, timestamp",
    "like": "count (incremento), total (acumulado), amount, userid, shortname",
    "join": "member_count, userid, shortname, user",
}
FALLBACK_LOADERS = ("fabric", "forge", "neoforge", "quilt")
DEFAULT_UNMATCHED_GIFT_COMMAND = (
    "execute as {player} at @s run summon minecraft:slime ~ ~ ~ {Size:4}"
)
DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE = "{usuario}: {interaccion} [{regla}]"
DEFAULT_COMMENT_CHAT_TEMPLATE = "{username}: {text}"


class RuleDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        on_save: Callable[[Rule], None],
        rule: Rule | None = None,
    ) -> None:
        super().__init__(master)
        self.title("Editar regla" if rule else "Crear regla")
        self.geometry("680x800")
        self.minsize(620, 700)
        self.resizable(False, False)
        self.on_save = on_save
        self.rule = rule
        self._default_message = ""
        self.transient(master)
        self.grab_set()

        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=16, pady=12)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text="Modo por bloques: elige evento y acción, sin tener que escribir "
            "comandos. Modo avanzado: edita el comando Minecraft directamente.",
            wraplength=590,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        ctk.CTkLabel(frame, text="Nombre para reconocer la regla").grid(
            row=1, column=0, sticky="w"
        )
        self.name_entry = ctk.CTkEntry(frame, placeholder_text="Nombre de la regla")
        self.name_entry.grid(row=2, column=0, sticky="ew", pady=(4, 10))

        ctk.CTkLabel(frame, text="¿Qué pasa en TikTok?").grid(
            row=3, column=0, sticky="w"
        )
        self.event_menu = ctk.CTkOptionMenu(
            frame,
            values=list(EVENT_TYPES_BY_LABEL),
            command=self._on_event_changed,
        )
        self.event_menu.grid(row=4, column=0, sticky="ew", pady=(4, 10))

        self.condition_help_label = ctk.CTkLabel(
            frame,
            text="Filtro opcional: completa los dos campos para reaccionar solo "
            "cuando coincida ese dato. Déjalos vacíos para aceptar cualquier "
            "evento del tipo elegido.",
            wraplength=590,
            justify="left",
        )
        self.condition_help_label.grid(row=5, column=0, sticky="w")
        self.condition_field_entry = ctk.CTkEntry(
            frame, placeholder_text="Campo JSON, por ejemplo text o gift_name"
        )
        self.condition_field_entry.grid(row=6, column=0, sticky="ew", pady=(4, 6))
        self.condition_value_entry = ctk.CTkComboBox(
            frame,
            values=getattr(master, "gift_catalog_names", []),
            state="normal",
            command=self._on_gift_selected,
        )
        self.condition_value_entry.grid(row=7, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(frame, text="Cómo configurar la acción").grid(
            row=8, column=0, sticky="w"
        )
        self.mode_menu = ctk.CTkOptionMenu(
            frame,
            values=["Por bloques (sencillo)", "Avanzado (comando)"],
            command=self._on_mode_changed,
        )
        self.mode_menu.grid(row=9, column=0, sticky="ew", pady=(4, 8))

        self.block_kind_label = ctk.CTkLabel(
            frame, text="Acción preconfigurada"
        )
        self.block_kind_label.grid(row=10, column=0, sticky="w")
        self.block_kind_menu = ctk.CTkOptionMenu(
            frame,
            values=[
                "Enviar mensaje al chat",
                "Invocar mobs",
                "Comando personalizado",
            ],
            command=self._on_block_kind_changed,
        )
        self.block_kind_menu.grid(row=11, column=0, sticky="ew", pady=(4, 8))

        self.chat_label = ctk.CTkLabel(
            frame, text="Mensaje para el chat de Minecraft"
        )
        self.chat_label.grid(row=12, column=0, sticky="w")
        self.chat_template_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Usa {text}, {usuario}, {gift} o {amount}",
        )
        self.chat_template_entry.grid(
            row=13, column=0, sticky="ew", pady=(4, 8)
        )
        self.entity_label = ctk.CTkLabel(
            frame,
            text="Entidad y cantidad a invocar",
        )
        self.entity_label.grid(row=14, column=0, sticky="w")
        entity_frame = ctk.CTkFrame(frame, fg_color="transparent")
        entity_frame.grid(row=15, column=0, sticky="ew", pady=(4, 8))
        entity_frame.grid_columnconfigure(0, weight=1)
        self.entity_entry = ctk.CTkEntry(
            entity_frame, placeholder_text="minecraft:zombie"
        )
        self.entity_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.spawn_count_entry = ctk.CTkEntry(
            entity_frame, width=130, placeholder_text="Cantidad"
        )
        self.spawn_count_entry.grid(row=0, column=1, sticky="ew")

        self.like_threshold_label = ctk.CTkLabel(
            frame, text="Invocar esta cantidad de mobs cada X likes"
        )
        self.like_threshold_label.grid(row=16, column=0, sticky="w")
        self.like_threshold_entry = ctk.CTkEntry(
            frame,
            placeholder_text="100 likes",
        )
        self.like_threshold_entry.grid(
            row=17, column=0, sticky="ew", pady=(4, 8)
        )

        self.action_help_label = ctk.CTkLabel(
            frame,
            text="",
            wraplength=590,
            justify="left",
        )
        self.action_help_label.grid(row=18, column=0, sticky="w", pady=(0, 8))

        self.command_label = ctk.CTkLabel(
            frame, text="Comando Minecraft (sin / inicial)"
        )
        self.command_label.grid(row=19, column=0, sticky="w")
        self.action_entry = ctk.CTkEntry(
            frame,
            placeholder_text="say Hola o summon minecraft:zombie ~ ~ ~",
        )
        self.action_entry.grid(row=20, column=0, sticky="ew", pady=(4, 4))
        self.variable_help_label = ctk.CTkLabel(
            frame,
            text="Variables: {username}, {user}, {usuario}, {player}, "
            "{shortname}, {userid}, {text}, {gift}, {giftname}, {amount}, "
            "{count}, {total}, {diamond_count}, {repeat_count}, {entity} "
            "y otros campos del evento. Cada línea se envía como un comando "
            "separado. {username} es TikTok; {player} es el selector de Minecraft.",
            wraplength=590,
            justify="left",
            text_color=("gray40", "gray70"),
        )
        self.variable_help_label.grid(
            row=21, column=0, sticky="w", pady=(0, 8)
        )
        self.repeat_label = ctk.CTkLabel(
            frame, text="Repeticiones del comando (1–64)"
        )
        self.repeat_label.grid(row=22, column=0, sticky="w")
        self.repeat_entry = ctk.CTkEntry(
            frame, placeholder_text="1 repetición"
        )
        self.repeat_entry.grid(row=23, column=0, sticky="ew", pady=(4, 8))
        self.repeat_by_amount_switch = ctk.CTkSwitch(
            frame,
            text="Repetir por cada unidad del regalo (multiplicar por amount)",
        )
        self.repeat_by_amount_switch.grid(
            row=24, column=0, sticky="w", pady=(0, 8)
        )
        self.enabled_switch = ctk.CTkSwitch(frame, text="Activar esta regla")
        self.enabled_switch.grid(row=25, column=0, sticky="w", pady=(0, 10))

        ctk.CTkButton(frame, text="Guardar regla", command=self._save).grid(
            row=26, column=0, sticky="ew"
        )

        if rule is not None:
            self.name_entry.insert(0, rule.name)
            self.event_menu.set(EVENT_LABELS.get(rule.event_type, rule.event_type))
            if rule.conditions:
                field_name, expected = next(iter(rule.conditions.items()))
                self.condition_field_entry.insert(0, field_name)
                self.condition_value_entry.insert(0, expected)
            self.mode_menu.set(
                "Por bloques (sencillo)"
                if rule.action_mode == "blocks"
                else "Avanzado (comando)"
            )
            self.block_kind_menu.set(
                {
                    "chat": "Enviar mensaje al chat",
                    "spawn": "Invocar mobs",
                    "command": "Comando personalizado",
                }.get(rule.action_kind, "Comando personalizado")
            )
            if rule.action_kind == "chat":
                self.chat_template_entry.insert(
                    0, rule.action.removeprefix("say ").strip()
                )
            elif rule.action_kind == "spawn":
                self.entity_entry.insert(0, rule.entity_id)
                self.spawn_count_entry.insert(0, str(rule.spawn_count))
            self.action_entry.insert(0, rule.action)
            self.like_threshold_entry.insert(0, str(rule.like_threshold))
            self.repeat_entry.insert(0, str(rule.repeat_count))
            if rule.repeat_by_amount:
                self.repeat_by_amount_switch.select()
            else:
                self.repeat_by_amount_switch.deselect()
            if rule.enabled:
                self.enabled_switch.select()
            else:
                self.enabled_switch.deselect()
        else:
            self.mode_menu.set("Por bloques (sencillo)")
            self.block_kind_menu.set("Enviar mensaje al chat")
            self.like_threshold_entry.insert(0, "100")
            self.spawn_count_entry.insert(0, "1")
            self.entity_entry.insert(0, "minecraft:zombie")
            self.repeat_entry.insert(0, "1")
            self._set_default_chat_template()
            self.enabled_switch.select()
        self._update_action_controls()

    def _on_event_changed(self, _label: str) -> None:
        self._set_default_chat_template()
        self._update_action_controls()

    def _on_gift_selected(self, gift_name: str) -> None:
        if gift_name and not self.condition_field_entry.get().strip():
            self.condition_field_entry.insert(0, "gift_name")

    def _set_default_chat_template(self) -> None:
        event_type = EVENT_TYPES_BY_LABEL.get(
            self.event_menu.get(), "comment"
        )
        new_default = ACTION_PRESETS[event_type]
        current = self.chat_template_entry.get()
        if not current or current == self._default_message:
            self.chat_template_entry.delete(0, "end")
            self.chat_template_entry.insert(0, new_default)
        self._default_message = new_default

    def _on_mode_changed(self, _mode: str) -> None:
        if (
            self.mode_menu.get() == "Avanzado (comando)"
            and not self.action_entry.get().strip()
        ):
            self.action_entry.insert(0, self._command_from_blocks())
        self._update_action_controls()

    def _on_block_kind_changed(self, _kind: str) -> None:
        if self.block_kind_menu.get() == "Enviar mensaje al chat":
            self._set_default_chat_template()
        elif (
            self.block_kind_menu.get() == "Invocar mobs"
            and not self.action_entry.get().strip()
        ):
            self.action_entry.insert(0, self._command_from_blocks())
        self._update_action_controls()

    def _command_from_blocks(self) -> str:
        if self.block_kind_menu.get() == "Enviar mensaje al chat":
            message = self.chat_template_entry.get().strip()
            return f"say {message}" if message else ""
        if self.block_kind_menu.get() == "Invocar mobs":
            return "summon {entity} ~ ~ ~"
        return self.action_entry.get().strip()

    def _update_action_controls(self) -> None:
        advanced = self.mode_menu.get() == "Avanzado (comando)"
        kind = self.block_kind_menu.get()
        is_chat = not advanced and kind == "Enviar mensaje al chat"
        is_spawn = not advanced and kind == "Invocar mobs"
        is_custom = advanced or kind == "Comando personalizado"
        is_like_spawn = (
            is_spawn
            and EVENT_TYPES_BY_LABEL.get(self.event_menu.get()) == "like"
        )
        event_type = EVENT_TYPES_BY_LABEL.get(self.event_menu.get(), "comment")
        example_field = EVENT_FIELDS[event_type].split(",", 1)[0].split()[0]
        self.condition_field_entry.configure(
            placeholder_text=f"Campo JSON de {EVENT_LABELS[event_type]}, "
            f"por ejemplo {example_field}"
        )
        if event_type == "gift":
            gift_names = getattr(self.master, "gift_catalog_names", [])
            self.condition_value_entry.configure(
                values=gift_names
            )
            catalog_status = (
                f"Catálogo TikTok cargado: {len(gift_names)} regalos."
                if gift_names
                else "Conecta TikTok LIVE para cargar regalos; también puedes "
                "escribir el nombre manualmente."
            )
            self.condition_help_label.configure(
                text=(
                    "Filtro de regalo: elige un regalo de la lista o escribe "
                    "su nombre. Se guardará como coincidencia exacta."
                    f"\n{catalog_status}"
                )
            )
        else:
            self.condition_value_entry.configure(
                values=getattr(self.master, "gift_catalog_names", [])
            )
            self.condition_help_label.configure(
                text=(
                    "Filtro opcional: completa los dos campos para reaccionar "
                    "solo cuando coincida ese dato. Déjalos vacíos para aceptar "
                    "cualquier evento del tipo elegido."
                )
            )
        is_spawn_action = kind == "Invocar mobs" or (
            advanced
            and self.rule is not None
            and self.rule.action_kind == "spawn"
        )
        show_repetitions = not is_spawn_action
        for widget in (self.block_kind_label, self.block_kind_menu):
            (widget.grid_remove if advanced else widget.grid)()
        for widget in (self.chat_label, self.chat_template_entry):
            (widget.grid if is_chat else widget.grid_remove)()
        for widget in (
            self.entity_label,
            self.entity_entry.master,
        ):
            (widget.grid if is_spawn else widget.grid_remove)()
        for widget in (self.like_threshold_label, self.like_threshold_entry):
            (widget.grid if is_like_spawn else widget.grid_remove)()
        for widget in (
            self.command_label,
            self.action_entry,
            self.variable_help_label,
        ):
            (widget.grid if is_custom else widget.grid_remove)()
        for widget in (self.repeat_label, self.repeat_entry):
            (widget.grid if show_repetitions else widget.grid_remove)()
        (
            self.repeat_by_amount_switch.grid
            if event_type == "gift"
            else self.repeat_by_amount_switch.grid_remove
        )()
        if advanced:
            help_text = (
                "Modo avanzado: admite execute, summon, give, fill, tp, tellraw, "
                "scoreboard y cualquier comando permitido por Minecraft. "
                "Puedes escribir varios comandos, uno por línea. API Bridge "
                "los recibe en orden, pero su HTTP confirma que quedaron "
                "encolados, no el resultado final dentro del juego."
            )
        elif is_chat:
            if event_type == "comment":
                help_text = (
                    "El comentario de TikTok se publica como texto en el chat de "
                    "Minecraft. Plantilla inicial: {text}. También puedes usar "
                    "{username} o {user}."
                )
            elif event_type == "gift":
                help_text = (
                    "Plantilla por defecto: {usuario} envió {gift} x{amount}. "
                    "También puedes usar {username}, {giftname}, {gift_id}, "
                    "{shortname}, {userid} y {count}."
                )
            else:
                help_text = "Puedes personalizar el mensaje con las variables indicadas."
        elif is_spawn:
            help_text = (
                "Usa el identificador Minecraft de la entidad, por ejemplo "
                "minecraft:zombie. En eventos de likes, configura el umbral abajo."
            )
        else:
            help_text = (
                "Comandos Java sin / inicial. {player} usa el selector/usuario "
                "Minecraft configurado; {username} es el nombre de TikTok y no "
                "identifica automáticamente la cuenta de Minecraft."
            )
        self.action_help_label.configure(
            text=f"{help_text}\nCampos de {EVENT_LABELS[event_type]}: "
            f"{EVENT_FIELDS.get(event_type, 'campos JSON del evento')}."
        )

    def _save(self) -> None:
        condition_field = self.condition_field_entry.get().strip()
        condition_value = self.condition_value_entry.get().strip()

        try:
            action_mode = (
                "blocks"
                if self.mode_menu.get() == "Por bloques (sencillo)"
                else "advanced"
            )
            block_kinds = {
                "Enviar mensaje al chat": "chat",
                "Invocar mobs": "spawn",
                "Comando personalizado": "command",
            }
            action_kind = (
                block_kinds.get(self.block_kind_menu.get(), "command")
                if action_mode == "blocks"
                else (
                    self.rule.action_kind
                    if self.rule is not None
                    else "command"
                )
            )
            if action_mode == "advanced":
                action = self.action_entry.get().strip()
            elif action_kind == "chat":
                message = self.chat_template_entry.get().strip()
                action = f"say {message}" if message else ""
            elif action_kind == "spawn":
                action = "summon {entity} ~ ~ ~"
            else:
                action = self.action_entry.get().strip()

            threshold = int(self.like_threshold_entry.get().strip() or "100")
            spawn_count = int(self.spawn_count_entry.get().strip() or "1")
            repeat_count = int(self.repeat_entry.get().strip() or "1")
            entity_id = self.entity_entry.get().strip() or "minecraft:zombie"
            event_type = EVENT_TYPES_BY_LABEL.get(
                self.event_menu.get(), self.event_menu.get().strip().lower()
            )
            if event_type == "gift" and condition_value and not condition_field:
                condition_field = "gift_name"
            if bool(condition_field) != bool(condition_value):
                messagebox.showerror(
                    "Condición incompleta",
                    "Completa tanto el campo de condición como su valor, o deja ambos vacíos.",
                    parent=self,
                )
                return
            conditions = (
                {condition_field: condition_value}
                if condition_field
                else {}
            )
            enabled = bool(self.enabled_switch.get())

            if self.rule is None:
                rule = Rule.create(
                    self.name_entry.get(),
                    event_type,
                    conditions,
                    action,
                    enabled=enabled,
                    action_mode=action_mode,
                    action_kind=action_kind,
                    like_threshold=threshold,
                    spawn_count=spawn_count,
                    entity_id=entity_id,
                    repeat_count=repeat_count,
                    repeat_by_amount=bool(self.repeat_by_amount_switch.get()),
                )
            else:
                rule = Rule(
                    id=self.rule.id,
                    name=self.name_entry.get().strip(),
                    event_type=event_type,
                    conditions=conditions,
                    action=action,
                    enabled=enabled,
                    action_mode=action_mode,
                    action_kind=action_kind,
                    like_threshold=threshold,
                    spawn_count=spawn_count,
                    entity_id=entity_id,
                    repeat_count=repeat_count,
                    repeat_by_amount=bool(self.repeat_by_amount_switch.get()),
                )
                if not rule.name or not rule.action:
                    raise ValueError("El nombre y la acción son obligatorios.")
                Rule.create(
                    rule.name,
                    rule.event_type,
                    rule.conditions,
                    rule.action,
                    enabled=rule.enabled,
                    action_mode=rule.action_mode,
                    action_kind=rule.action_kind,
                    like_threshold=rule.like_threshold,
                    spawn_count=rule.spawn_count,
                    entity_id=rule.entity_id,
                    repeat_count=rule.repeat_count,
                    repeat_by_amount=rule.repeat_by_amount,
                )
            self.on_save(rule)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Regla no válida", str(exc), parent=self)
            return
        self.destroy()


class Free2PlayApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Free2Play")
        self.geometry("1180x780")
        self.minsize(960, 640)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="free2play"
        )
        self.rule_store = RuleStore(RULES_PATH)
        self.profile_store = RuleProfileStore(PROFILES_PATH)
        self.profiles: list[RuleProfile] = []
        self.active_profile_name = "dani"
        self.settings_store = AppSettingsStore()
        self.preferences_error: str | None = None
        try:
            self.preferences = self.settings_store.load_preferences()
        except (OSError, ValueError) as exc:
            self.preferences = {}
            self.preferences_error = str(exc)
        self.vip_config_error: str | None = None
        try:
            self.VIP = self.settings_store.load_vip()
        except (OSError, ValueError) as exc:
            self.VIP = False
            self.vip_config_error = str(exc)
        self.rules: list[Rule] = []
        self.rule_engine = RuleEngine(self.rules)
        self.selected_rule_id: str | None = None
        self.api_token: str | None = None
        self.gift_catalog_names: list[str] = []
        self.forwarded_comment_ids: set[str] = set()
        self.forwarded_comment_order: deque[str] = deque(maxlen=4096)
        self.instance_dir: Path | None = None
        self.tiktok_process: subprocess.Popen[str] | None = None
        self.tiktok_thread: threading.Thread | None = None
        self.tiktok_generation = 0
        self.tiktok_stop_requested = False
        self.tiktok_connected_for_generation = False
        self.tiktok_state = "disconnected"
        self.minecraft_state = "disconnected"
        self._minecraft_check_in_progress = False
        self.automation_running = False
        self.log_rows: list[tuple[str, str, str, str, str]] = []
        self.events_processed = 0
        self.likes_received = 0
        self.commands_sent = 0
        self.current_activity = "Aplicación iniciada"
        self.last_event_description = "Ninguno"
        self._cpu_last_wall = time.perf_counter()
        self._cpu_last_process = time.process_time()
        self._cpu_percent = 0.0
        self._closing = False
        self._queue_after_id: str | None = None
        self._monitor_after_id: str | None = None
        self._startup_connect_after_id: str | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_content()
        self._restore_preferences()
        self._update_plan_display()
        self._load_rules()
        self._show_page("Inicio")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._queue_after_id = self.after(100, self._process_queue)
        self._monitor_after_id = self.after(1000, self._update_advanced_monitor)
        if (
            self.preferences.get("auto_connect_tiktok", True)
            and self.preferences.get("tiktok_username")
        ):
            self._startup_connect_after_id = self.after(
                500, self._connect_tiktok
            )

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=205, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(8, weight=1)
        ctk.CTkLabel(
            self.sidebar,
            text="Free2Play",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(28, 30), sticky="w")

        for row, name in enumerate(
            ("Inicio", "TikTok LIVE", "Minecraft", "Reglas", "Registro", "Configuración"),
            start=1,
        ):
            ctk.CTkButton(
                self.sidebar,
                text=name,
                anchor="w",
                command=lambda page=name: self._show_page(page),
            ).grid(row=row, column=0, padx=14, pady=5, sticky="ew")

        self.monitor_nav_button = ctk.CTkButton(
            self.sidebar,
            text="Monitor avanzado",
            anchor="w",
            command=lambda: self._show_page("Monitor avanzado"),
        )
        self.monitor_nav_button.grid(row=7, column=0, padx=14, pady=5, sticky="ew")
        self.monitor_nav_button.grid_remove()
        ctk.CTkLabel(
            self.sidebar,
            text="Eventos y acciones se\nprocesan localmente.",
            justify="left",
            text_color=("gray40", "gray70"),
        ).grid(row=9, column=0, padx=18, pady=22, sticky="sw")

    def _build_content(self) -> None:
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=22, pady=20)
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.page_title = ctk.CTkLabel(
            self.content,
            text="Inicio",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.page_title.grid(row=0, column=0, sticky="w", pady=(0, 14))
        self.page_container = ctk.CTkFrame(self.content, fg_color="transparent")
        self.page_container.grid(row=1, column=0, sticky="nsew")
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        builders = {
            "Inicio": self._build_home_page,
            "TikTok LIVE": self._build_tiktok_page,
            "Minecraft": self._build_minecraft_page,
            "Reglas": self._build_rules_page,
            "Registro": self._build_log_page,
            "Configuración": self._build_settings_page,
            "Monitor avanzado": self._build_advanced_monitor_page,
        }
        for name, builder in builders.items():
            page = ctk.CTkFrame(self.page_container, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_columnconfigure(0, weight=1)
            self.pages[name] = page
            builder(page)

    def _show_page(self, name: str) -> None:
        self.page_title.configure(text=name)
        self.pages[name].tkraise()

    @staticmethod
    def _section(
        parent: ctk.CTkFrame, title: str, row: int, column: int = 0
    ) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=row, column=column, padx=6, pady=6, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")
        return frame

    def _build_home_page(self, page: ctk.CTkFrame) -> None:
        for column in range(3):
            page.grid_columnconfigure(column, weight=1)
        self.status_labels: dict[str, ctk.CTkLabel] = {}
        for column, (key, title) in enumerate(
            (
                ("tiktok", "TikTok LIVE"),
                ("minecraft", "Minecraft"),
                ("automation", "Automatización"),
            )
        ):
            card = self._section(page, title, 0, column)
            label = ctk.CTkLabel(card, text="Desconectado")
            label.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
            self.status_labels[key] = label

        actions = self._section(page, "Acciones", 1)
        for column in range(2):
            actions.grid_columnconfigure(column, weight=1)
        self.home_tiktok_button = ctk.CTkButton(
            actions, text="Conectar TikTok", command=self._toggle_tiktok
        )
        self.home_tiktok_button.grid(
            row=1, column=0, padx=16, pady=7, sticky="ew"
        )
        ctk.CTkButton(
            actions,
            text="Conectar Minecraft",
            command=self._connect_minecraft,
        ).grid(row=1, column=1, padx=16, pady=7, sticky="ew")
        ctk.CTkButton(
            actions,
            text="Probar conexión Minecraft",
            command=self._test_minecraft_connection,
        ).grid(row=2, column=0, padx=16, pady=7, sticky="ew")
        self.home_automation_button = ctk.CTkButton(
            actions,
            text="Iniciar automatización",
            command=self._toggle_automation,
        )
        self.home_automation_button.grid(
            row=2, column=1, padx=16, pady=7, sticky="ew"
        )

        recent = self._section(page, "Actividad reciente", 2)
        recent.grid_rowconfigure(1, weight=1)
        page.grid_rowconfigure(2, weight=1)
        self.recent_activity = ctk.CTkTextbox(recent, height=210, wrap="word")
        self.recent_activity.grid(
            row=1, column=0, padx=14, pady=(0, 14), sticky="nsew"
        )
        self.recent_activity.configure(state="disabled")

    def _build_tiktok_page(self, page: ctk.CTkFrame) -> None:
        frame = self._section(page, "Conexión a TikTok LIVE", 0)
        ctk.CTkLabel(
            frame,
            text=(
                "Puedes guardar el usuario e intentar conectarte al abrir Free2Play. "
                "Si falla, la app mostrará el error y podrás reintentar manualmente."
            ),
            wraplength=700,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        self.tiktok_username_entry = ctk.CTkEntry(
            frame, placeholder_text="Nombre de usuario (con o sin @)"
        )
        self.tiktok_username_entry.grid(
            row=2, column=0, padx=16, pady=6, sticky="ew"
        )
        self.tiktok_username_entry.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )
        self.tiktok_page_status = ctk.CTkLabel(frame, text="Desconectado")
        self.tiktok_page_status.grid(
            row=3, column=0, padx=16, pady=6, sticky="w"
        )
        self.tiktok_page_button = ctk.CTkButton(
            frame, text="Conectar", command=self._toggle_tiktok
        )
        self.tiktok_page_button.grid(
            row=4, column=0, padx=16, pady=(6, 16), sticky="w"
        )
        self.auto_connect_switch = ctk.CTkSwitch(
            frame,
            text="Intentar conectar al iniciar la aplicación",
            command=self._on_auto_connect_changed,
        )
        self.auto_connect_switch.grid(
            row=5, column=0, padx=16, pady=(0, 14), sticky="w"
        )

    def _build_minecraft_page(self, page: ctk.CTkFrame) -> None:
        page.grid_rowconfigure(3, weight=1)
        install = self._section(page, "Instalar o actualizar API Bridge", 0)
        install.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(install, text="Versión de Minecraft").grid(
            row=1, column=0, padx=16, pady=6, sticky="w"
        )
        self.minecraft_version_combo = ctk.CTkComboBox(
            install,
            values=[],
            state="normal",
        )
        self.minecraft_version_combo.set("")
        self.minecraft_version_combo.grid(
            row=1, column=1, padx=16, pady=6, sticky="ew"
        )
        self.minecraft_version_combo.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )
        ctk.CTkLabel(install, text="Mod loader").grid(
            row=2, column=0, padx=16, pady=6, sticky="w"
        )
        self.loader_menu = ctk.CTkOptionMenu(
            install,
            values=list(FALLBACK_LOADERS),
            command=lambda _value: self._save_user_preferences(),
        )
        self.loader_menu.set("fabric")
        self.loader_menu.grid(row=2, column=1, padx=16, pady=6, sticky="w")

        ctk.CTkLabel(install, text="Carpeta de instancia").grid(
            row=3, column=0, padx=16, pady=6, sticky="w"
        )
        self.instance_path_entry = ctk.CTkEntry(
            install, placeholder_text="Selecciona o pega la carpeta de la instancia"
        )
        self.instance_path_entry.grid(
            row=3, column=1, padx=16, pady=6, sticky="ew"
        )
        ctk.CTkButton(
            install, text="Seleccionar…", command=self._browse_instance
        ).grid(row=3, column=2, padx=(0, 16), pady=6)
        self.install_status = ctk.CTkLabel(install, text="Esperando selección.")
        self.install_status.grid(
            row=4, column=0, columnspan=3, padx=16, pady=6, sticky="w"
        )
        self.install_button = ctk.CTkButton(
            install,
            text="Descargar API Bridge en mods",
            command=self._install_mod,
        )
        self.install_button.grid(
            row=5, column=0, columnspan=3, padx=16, pady=(6, 16), sticky="ew"
        )
        self.install_force_switch = ctk.CTkSwitch(
            install, text="Permitir reemplazar un JAR con distinto hash"
        )
        self.install_force_switch.grid(
            row=6, column=0, columnspan=3, padx=16, pady=(0, 14), sticky="w"
        )

        connection = self._section(page, "Conexión a una instancia iniciada", 1)
        connection.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(connection, text="Dirección base del API").grid(
            row=1, column=0, padx=16, pady=6, sticky="w"
        )
        self.api_url_entry = ctk.CTkEntry(connection)
        self.api_url_entry.insert(0, "http://127.0.0.1:25566")
        self.api_url_entry.grid(
            row=1, column=1, padx=16, pady=6, sticky="ew"
        )
        self.api_url_entry.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )
        self.token_status = ctk.CTkLabel(
            connection, text="Token: no cargado (no se mostrará en pantalla)"
        )
        self.token_status.grid(
            row=2, column=0, columnspan=2, padx=16, pady=6, sticky="w"
        )
        token_buttons = ctk.CTkFrame(connection, fg_color="transparent")
        token_buttons.grid(
            row=3, column=0, columnspan=2, padx=16, pady=(6, 14), sticky="ew"
        )
        self.get_token_button = ctk.CTkButton(
            token_buttons, text="Obtener token del log", command=self._get_token
        )
        self.get_token_button.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            token_buttons,
            text="Conectar Minecraft",
            command=self._connect_minecraft,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            token_buttons,
            text="Probar conexión",
            command=self._test_minecraft_connection,
        ).pack(side="left", padx=8)
        ctk.CTkLabel(
            connection,
            text="La prueba consulta GET /api/ con Authorization: Bearer <token>.",
            wraplength=740,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 14), sticky="w")

        ctk.CTkLabel(connection, text="Jugador/selector objetivo").grid(
            row=5, column=0, padx=16, pady=6, sticky="w"
        )
        self.minecraft_target_entry = ctk.CTkEntry(
            connection,
            placeholder_text="@a o nombre exacto del jugador Minecraft",
        )
        self.minecraft_target_entry.insert(0, "@a")
        self.minecraft_target_entry.grid(
            row=5, column=1, padx=16, pady=6, sticky="ew"
        )
        self.minecraft_target_entry.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )
        self.debug_commands_switch = ctk.CTkSwitch(
            connection,
            text=(
                "Depuración HTTP: registrar el comando y la respuesta "
                "completa de API Bridge"
            ),
            command=self._on_debug_commands_changed,
        )
        self.debug_commands_switch.grid(
            row=6, column=0, columnspan=2, padx=16, pady=(4, 12), sticky="w"
        )

        ctk.CTkLabel(
            page,
            text=(
                "La descarga instala únicamente el JAR de API Bridge en la carpeta "
                "mods. No inicia Minecraft ni instala otros mods o dependencias."
            ),
            wraplength=800,
            justify="left",
        ).grid(row=2, column=0, padx=8, pady=8, sticky="w")

    def _build_rules_page(self, page: ctk.CTkFrame) -> None:
        page.grid_rowconfigure(0, weight=1)
        frame = self._section(page, "Reglas de automatización", 0)
        frame.grid_rowconfigure(4, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=(
                "Guía rápida: 1) Conecta TikTok LIVE y Minecraft. 2) Pulsa Crear "
                "y elige el modo por bloques o avanzado. 3) Para una regla de "
                "likes, elige Invocar mobs e indica la cantidad cada X likes. "
                "Deja el filtro vacío para "
                "aceptar cualquier evento de ese tipo, o usa un campo como text "
                "(comentario), gift_name (nombre del regalo) o shortname "
                "(usuario). 4) Elige un mensaje de ejemplo o escribe un comando "
                "Minecraft sin / y guarda. Usa {username} para TikTok, {player} "
                "para el objetivo Minecraft, {gift_name} para identificar "
                "regalos y {amount} para cuántos llegaron. Puedes escribir "
                "varios comandos, uno por línea. 5) Pulsa Probar coincidencia para "
                "revisar el filtro; esto no envía el comando. Finalmente, inicia "
                "la automatización desde Inicio. Las variables se rellenan con "
                "los datos recibidos de TikTok. La respuesta de API Bridge "
                "confirma que se encoló, no que el comando terminó."
            ),
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        profile_bar = ctk.CTkFrame(frame, fg_color="transparent")
        profile_bar.grid(row=2, column=0, padx=14, pady=4, sticky="ew")
        profile_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(profile_bar, text="Perfil activo").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.profile_menu = ctk.CTkOptionMenu(
            profile_bar,
            values=["dani"],
            command=self._switch_profile,
        )
        self.profile_menu.grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(
            profile_bar,
            text="Crear perfil desde este",
            command=self._create_profile,
        ).grid(row=0, column=2, padx=(8, 0), sticky="ew")
        self.profile_status = ctk.CTkLabel(
            frame,
            text=(
                "Los comandos del perfil Dani pueden modificar el mundo; "
                "pruébalos en un mundo seguro."
            ),
            wraplength=820,
            justify="left",
            text_color=("gray40", "gray70"),
        )
        self.profile_status.grid(
            row=3, column=0, padx=16, pady=(0, 6), sticky="w"
        )
        self.rules_list = ctk.CTkScrollableFrame(frame, height=390)
        self.rules_list.grid(
            row=4, column=0, padx=14, pady=6, sticky="nsew"
        )
        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=5, column=0, padx=14, pady=(8, 14), sticky="ew")
        for column in range(5):
            buttons.grid_columnconfigure(column, weight=1)
        ctk.CTkButton(
            buttons, text="Crear", command=self._create_rule
        ).grid(row=0, column=0, padx=4, sticky="ew")
        ctk.CTkButton(
            buttons, text="Editar", command=self._edit_rule
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(
            buttons, text="Activar / desactivar", command=self._toggle_rule
        ).grid(row=0, column=2, padx=4, sticky="ew")
        ctk.CTkButton(
            buttons, text="Eliminar", command=self._delete_rule
        ).grid(row=0, column=3, padx=4, sticky="ew")
        ctk.CTkButton(
            buttons, text="Probar coincidencia", command=self._test_rule
        ).grid(row=0, column=4, padx=4, sticky="ew")

    def _build_log_page(self, page: ctk.CTkFrame) -> None:
        page.grid_rowconfigure(0, weight=1)
        frame = self._section(page, "Registro de actividad", 0)
        frame.grid_rowconfigure(1, weight=1)
        self.log_textbox = ctk.CTkTextbox(frame, wrap="none")
        self.log_textbox.grid(
            row=1, column=0, padx=14, pady=(0, 14), sticky="nsew"
        )
        self.log_textbox.configure(state="disabled")

    def _build_settings_page(self, page: ctk.CTkFrame) -> None:
        settings_content = ctk.CTkScrollableFrame(
            page, fg_color="transparent"
        )
        settings_content.grid(row=0, column=0, sticky="nsew")
        page.grid_rowconfigure(0, weight=1)
        page.grid_columnconfigure(0, weight=1)

        frame = self._section(settings_content, "Apariencia", 0)
        ctk.CTkLabel(frame, text="Tema").grid(
            row=1, column=0, padx=16, pady=6, sticky="w"
        )
        ctk.CTkOptionMenu(
            frame,
            values=["dark", "light", "system"],
            command=ctk.set_appearance_mode,
        ).grid(row=2, column=0, padx=16, pady=(0, 16), sticky="w")

        plan_frame = self._section(
            settings_content, "Plan de la aplicación", 1
        )
        self.plan_label = ctk.CTkLabel(plan_frame, text="")
        self.plan_label.grid(
            row=1, column=0, padx=16, pady=(0, 8), sticky="w"
        )
        self.vip_switch = ctk.CTkSwitch(
            plan_frame,
            text="VIP",
            command=self._save_vip_setting,
        )
        self.vip_switch.grid(
            row=2, column=0, padx=16, pady=(0, 12), sticky="w"
        )
        if self.VIP:
            self.vip_switch.select()
        else:
            self.vip_switch.deselect()
        self.vip_config_status = ctk.CTkLabel(
            plan_frame,
            text=(
                self.vip_config_error
                or "El valor se guarda cifrado para este usuario de Windows."
            ),
            wraplength=760,
            justify="left",
        )
        self.vip_config_status.grid(
            row=3, column=0, padx=16, pady=(0, 14), sticky="w"
        )
        experience = self._section(
            settings_content, "Preferencias de conexión e interfaz", 2
        )
        ctk.CTkLabel(
            experience,
            text="El nombre de usuario y la carpeta de la instancia se guardan "
            "localmente. El nombre de TikTok no es una contraseña.",
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        self.advanced_interface_switch = ctk.CTkSwitch(
            experience,
            text="Mostrar monitor avanzado (CPU, eventos y acciones)",
            command=self._on_advanced_interface_changed,
        )
        self.advanced_interface_switch.grid(
            row=2, column=0, padx=16, pady=(0, 14), sticky="w"
        )
        self.preferences_status = ctk.CTkLabel(
            experience,
            text=self.preferences_error or "Preferencias guardadas en este equipo.",
            wraplength=760,
            justify="left",
        )
        self.preferences_status.grid(
            row=3, column=0, padx=16, pady=(0, 12), sticky="w"
        )
        unmatched_gifts = self._section(
            settings_content, "Regalos sin regla", 3
        )
        ctk.CTkLabel(
            unmatched_gifts,
            text=(
                "Si llega un regalo sin ninguna regla activa que coincida, "
                "puedes usar esta acción alternativa. Solo funciona con la "
                "automatización activa y está desactivada por defecto."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        self.unmatched_gift_fallback_switch = ctk.CTkSwitch(
            unmatched_gifts,
            text="Activar acción para regalos sin regla",
            command=self._on_unmatched_gift_fallback_changed,
        )
        self.unmatched_gift_fallback_switch.grid(
            row=2, column=0, padx=16, pady=(0, 8), sticky="w"
        )
        ctk.CTkLabel(
            unmatched_gifts,
            text="Comando Minecraft (sin / inicial; por defecto invoca un slime grande)",
        ).grid(row=3, column=0, padx=16, pady=(0, 4), sticky="w")
        self.unmatched_gift_command_entry = ctk.CTkEntry(
            unmatched_gifts,
            placeholder_text=DEFAULT_UNMATCHED_GIFT_COMMAND,
        )
        self.unmatched_gift_command_entry.insert(
            0, DEFAULT_UNMATCHED_GIFT_COMMAND
        )
        self.unmatched_gift_command_entry.grid(
            row=4, column=0, padx=16, pady=(0, 14), sticky="ew"
        )
        self.unmatched_gift_command_entry.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )
        ctk.CTkLabel(
            settings_content,
            text=(
                f"Perfiles de reglas: {PROFILES_PATH}\n"
                f"Reglas heredadas conservadas: {RULES_PATH}"
            ),
            wraplength=820,
            justify="left",
        ).grid(row=5, column=0, padx=8, pady=12, sticky="w")

        announcements = self._section(
            settings_content, "Anuncios de reglas en el chat", 4
        )
        ctk.CTkLabel(
            announcements,
            text=(
                "Al coincidir una regla, envía un mensaje a todos los jugadores "
                "en color morado. Las variables se rellenan con el evento y el "
                "nombre de la regla."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        self.rule_announcement_switch = ctk.CTkSwitch(
            announcements,
            text="Anunciar cuando se active una regla",
            command=self._on_rule_announcement_changed,
        )
        self.rule_announcement_switch.grid(
            row=2, column=0, padx=16, pady=(0, 8), sticky="w"
        )
        ctk.CTkLabel(
            announcements,
            text=(
                "Plantilla. Variables: {usuario}, {gift_name}, {amount}, "
                "{text}, {count}, {regla}, {interaccion}."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=3, column=0, padx=16, pady=(0, 4), sticky="w")
        self.rule_announcement_template_entry = ctk.CTkEntry(
            announcements,
            placeholder_text=DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE,
        )
        self.rule_announcement_template_entry.insert(
            0, DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE
        )
        self.rule_announcement_template_entry.grid(
            row=4, column=0, padx=16, pady=(0, 8), sticky="ew"
        )
        self.rule_announcement_template_entry.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )
        ctk.CTkLabel(
            announcements,
            text="Color del texto",
        ).grid(row=5, column=0, padx=16, pady=(0, 4), sticky="w")
        self.rule_announcement_color_menu = ctk.CTkOptionMenu(
            announcements,
            values=["light_purple", "dark_purple"],
            command=lambda _value: self._save_user_preferences(),
        )
        self.rule_announcement_color_menu.set("light_purple")
        self.rule_announcement_color_menu.grid(
            row=6, column=0, padx=16, pady=(0, 14), sticky="w"
        )
        comment_chat = self._section(
            settings_content, "Comentarios de TikTok en Minecraft", 5
        )
        ctk.CTkLabel(
            comment_chat,
            text=(
                "Publica cada comentario en el chat de Minecraft incluso si "
                "la automatización de reglas está pausada. Se usa tellraw para "
                "mostrar el texto normalmente, no como JSON ni como comando."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        self.comment_chat_switch = ctk.CTkSwitch(
            comment_chat,
            text="Enviar comentarios al chat de Minecraft",
            command=self._on_comment_chat_changed,
        )
        self.comment_chat_switch.grid(
            row=2, column=0, padx=16, pady=(0, 8), sticky="w"
        )
        ctk.CTkLabel(
            comment_chat,
            text="Formato (variables disponibles: {username}, {shortname}, {text})",
        ).grid(row=3, column=0, padx=16, pady=(0, 4), sticky="w")
        self.comment_chat_template_entry = ctk.CTkEntry(
            comment_chat,
            placeholder_text=DEFAULT_COMMENT_CHAT_TEMPLATE,
        )
        self.comment_chat_template_entry.insert(
            0, DEFAULT_COMMENT_CHAT_TEMPLATE
        )
        self.comment_chat_template_entry.grid(
            row=4, column=0, padx=16, pady=(0, 14), sticky="ew"
        )
        self.comment_chat_template_entry.bind(
            "<FocusOut>", lambda _event: self._save_user_preferences()
        )

    def _build_advanced_monitor_page(self, page: ctk.CTkFrame) -> None:
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        overview = self._section(page, "Estado en tiempo real", 0)
        overview.grid_columnconfigure(1, weight=1)
        self.monitor_values: dict[str, ctk.CTkLabel] = {}
        monitor_rows = (
            ("cpu", "Uso CPU de Free2Play"),
            ("tiktok", "TikTok LIVE"),
            ("minecraft", "Minecraft / API Bridge"),
            ("automation", "Automatización"),
            ("events", "Eventos recibidos"),
            ("likes", "Likes acumulados"),
            ("commands", "Comandos encolados en API Bridge"),
            ("last_event", "Último evento"),
            ("activity", "Actividad actual"),
        )
        for row, (key, label_text) in enumerate(monitor_rows, start=1):
            ctk.CTkLabel(overview, text=label_text).grid(
                row=row, column=0, padx=16, pady=5, sticky="w"
            )
            value = ctk.CTkLabel(overview, text="—", anchor="w")
            value.grid(row=row, column=1, padx=16, pady=5, sticky="ew")
            self.monitor_values[key] = value
        recent = self._section(page, "Registro detallado", 1)
        recent.grid_rowconfigure(1, weight=1)
        self.advanced_log_textbox = ctk.CTkTextbox(
            recent, height=220, wrap="word"
        )
        self.advanced_log_textbox.grid(
            row=1, column=0, padx=14, pady=(0, 14), sticky="nsew"
        )
        self.advanced_log_textbox.configure(state="disabled")

    def _restore_preferences(self) -> None:
        username = str(self.preferences.get("tiktok_username", "")).strip()
        if username:
            self.tiktok_username_entry.insert(0, username)
        if self.preferences.get("auto_connect_tiktok", True):
            self.auto_connect_switch.select()
        else:
            self.auto_connect_switch.deselect()

        instance_dir = str(self.preferences.get("instance_dir", "")).strip()
        if instance_dir:
            self.instance_path_entry.insert(0, instance_dir)
            self.instance_dir = Path(instance_dir).expanduser()

        minecraft_version = str(
            self.preferences.get("minecraft_version", "")
        ).strip()
        if minecraft_version and not minecraft_version.startswith(
            "Escribe una versión"
        ):
            self.minecraft_version_combo.set(minecraft_version)
        loader = str(self.preferences.get("modloader", "fabric")).strip().lower()
        if loader in FALLBACK_LOADERS:
            self.loader_menu.set(loader)
        api_url = str(self.preferences.get("api_url", "")).strip()
        if api_url:
            self.api_url_entry.delete(0, "end")
            self.api_url_entry.insert(0, api_url)
        minecraft_target = str(
            self.preferences.get("minecraft_target", "@a")
        ).strip()
        if minecraft_target:
            self.minecraft_target_entry.delete(0, "end")
            self.minecraft_target_entry.insert(0, minecraft_target)
        if self.preferences.get("debug_commands", False):
            self.debug_commands_switch.select()
        else:
            self.debug_commands_switch.deselect()
        unmatched_command = str(
            self.preferences.get(
                "unmatched_gift_command",
                DEFAULT_UNMATCHED_GIFT_COMMAND,
            )
        ).strip() or DEFAULT_UNMATCHED_GIFT_COMMAND
        if unmatched_command != DEFAULT_UNMATCHED_GIFT_COMMAND:
            self.unmatched_gift_command_entry.delete(0, "end")
            self.unmatched_gift_command_entry.insert(0, unmatched_command)
        if self.preferences.get("unmatched_gift_fallback_enabled", False):
            self.unmatched_gift_fallback_switch.select()
        else:
            self.unmatched_gift_fallback_switch.deselect()
        if self.preferences.get("rule_announcement_enabled", True):
            self.rule_announcement_switch.select()
        else:
            self.rule_announcement_switch.deselect()
        if self.preferences.get("comment_chat_enabled", True):
            self.comment_chat_switch.select()
        else:
            self.comment_chat_switch.deselect()
        comment_chat_template = str(
            self.preferences.get(
                "comment_chat_template",
                DEFAULT_COMMENT_CHAT_TEMPLATE,
            )
        ).strip() or DEFAULT_COMMENT_CHAT_TEMPLATE
        if comment_chat_template != DEFAULT_COMMENT_CHAT_TEMPLATE:
            self.comment_chat_template_entry.delete(0, "end")
            self.comment_chat_template_entry.insert(0, comment_chat_template)
        announcement_template = str(
            self.preferences.get(
                "rule_announcement_template",
                DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE,
            )
        ).strip() or DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE
        if announcement_template != DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE:
            self.rule_announcement_template_entry.delete(0, "end")
            self.rule_announcement_template_entry.insert(
                0, announcement_template
            )
        announcement_color = str(
            self.preferences.get("rule_announcement_color", "light_purple")
        )
        if announcement_color in {"light_purple", "dark_purple"}:
            self.rule_announcement_color_menu.set(announcement_color)

        show_advanced = bool(self.preferences.get("show_advanced", False))
        if show_advanced:
            self.advanced_interface_switch.select()
            self.monitor_nav_button.grid()
        else:
            self.advanced_interface_switch.deselect()
            self.monitor_nav_button.grid_remove()
        self._update_advanced_monitor_values()

    def _save_user_preferences(self) -> None:
        if not hasattr(self, "tiktok_username_entry"):
            return
        self.preferences.update(
            {
                "tiktok_username": self.tiktok_username_entry.get().strip(),
                "auto_connect_tiktok": bool(self.auto_connect_switch.get()),
                "instance_dir": self.instance_path_entry.get().strip(),
                "minecraft_version": self.minecraft_version_combo.get().strip(),
                "modloader": self.loader_menu.get().strip().lower(),
                "api_url": self.api_url_entry.get().strip(),
                "minecraft_target": (
                    self.minecraft_target_entry.get().strip() or "@a"
                ),
                "debug_commands": bool(self.debug_commands_switch.get()),
                "show_advanced": bool(self.advanced_interface_switch.get()),
                "unmatched_gift_fallback_enabled": bool(
                    self.unmatched_gift_fallback_switch.get()
                ),
                "unmatched_gift_command": (
                    self.unmatched_gift_command_entry.get().strip()
                    or DEFAULT_UNMATCHED_GIFT_COMMAND
                ),
                "rule_announcement_enabled": bool(
                    self.rule_announcement_switch.get()
                ),
                "comment_chat_enabled": bool(self.comment_chat_switch.get()),
                "comment_chat_template": (
                    self.comment_chat_template_entry.get().strip()
                    or DEFAULT_COMMENT_CHAT_TEMPLATE
                ),
                "rule_announcement_template": (
                    self.rule_announcement_template_entry.get().strip()
                    or DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE
                ),
                "rule_announcement_color": (
                    self.rule_announcement_color_menu.get()
                ),
                "active_profile": self.active_profile_name,
            }
        )
        try:
            self.settings_store.save_preferences(self.preferences)
        except (OSError, TypeError, ValueError) as exc:
            if hasattr(self, "preferences_status"):
                self.preferences_status.configure(
                    text=f"No se pudieron guardar las preferencias: {exc}"
                )
            self._log(
                "Configuración",
                "No se pudieron guardar las preferencias",
                detail=str(exc),
            )
            return
        if hasattr(self, "preferences_status"):
            self.preferences_status.configure(
                text="Preferencias guardadas en este equipo."
            )

    def _on_auto_connect_changed(self) -> None:
        self._save_user_preferences()

    def _on_debug_commands_changed(self) -> None:
        enabled = bool(self.debug_commands_switch.get())
        self._log(
            "Depuración",
            "Depuración HTTP activada" if enabled else "Depuración HTTP desactivada",
            detail=(
                "Se registrarán comandos y cuerpos de respuesta de API Bridge; "
                "el token se mantendrá oculto."
                if enabled
                else ""
            ),
        )
        self._save_user_preferences()

    def _on_unmatched_gift_fallback_changed(self) -> None:
        enabled = bool(self.unmatched_gift_fallback_switch.get())
        command = self.unmatched_gift_command_entry.get().strip()
        if enabled and not command:
            self.unmatched_gift_fallback_switch.deselect()
            messagebox.showwarning(
                "Falta el comando",
                "Escribe un comando Minecraft antes de activar esta acción.",
                parent=self,
            )
            return
        self._save_user_preferences()
        self._log(
            "Configuración",
            (
                "Acción alternativa para regalos activada"
                if enabled
                else "Acción alternativa para regalos desactivada"
            ),
            detail=(
                "Se usará solo si ninguna regla activa coincide con el regalo."
                if enabled
                else ""
            ),
        )

    def _on_rule_announcement_changed(self) -> None:
        enabled = bool(self.rule_announcement_switch.get())
        self._save_user_preferences()
        self._log(
            "Configuración",
            (
                "Anuncios de activación de reglas activados"
                if enabled
                else "Anuncios de activación de reglas desactivados"
            ),
            detail=(
                "Los mensajes se enviarán al chat de Minecraft en color morado."
                if enabled
                else ""
            ),
        )

    def _on_comment_chat_changed(self) -> None:
        enabled = bool(self.comment_chat_switch.get())
        self._save_user_preferences()
        self._log(
            "Configuración",
            (
                "Envío de comentarios a Minecraft activado"
                if enabled
                else "Envío de comentarios a Minecraft desactivado"
            ),
            detail=(
                "Los comentarios se publicarán aunque las reglas estén pausadas."
                if enabled
                else ""
            ),
        )

    def _on_advanced_interface_changed(self) -> None:
        if self.advanced_interface_switch.get():
            self.monitor_nav_button.grid()
            self._log("Monitor", "Interfaz avanzada activada")
        else:
            self.monitor_nav_button.grid_remove()
            if self.page_title.cget("text") == "Monitor avanzado":
                self._show_page("Configuración")
            self._log("Monitor", "Interfaz avanzada desactivada")
        self._save_user_preferences()
        self._update_advanced_monitor_values()

    def _update_advanced_monitor_values(self) -> None:
        if not hasattr(self, "monitor_values"):
            return
        self.monitor_values["cpu"].configure(text=f"{self._cpu_percent:.1f}%")
        self.monitor_values["tiktok"].configure(
            text=self.tiktok_state.capitalize()
        )
        self.monitor_values["minecraft"].configure(
            text=self.minecraft_state.capitalize()
        )
        self.monitor_values["automation"].configure(
            text="Activa" if self.automation_running else "Pausada"
        )
        self.monitor_values["events"].configure(text=str(self.events_processed))
        self.monitor_values["likes"].configure(text=str(self.likes_received))
        self.monitor_values["commands"].configure(text=str(self.commands_sent))
        self.monitor_values["last_event"].configure(
            text=self.last_event_description
        )
        self.monitor_values["activity"].configure(text=self.current_activity)

    def _update_advanced_monitor(self) -> None:
        self._monitor_after_id = None
        if self._closing:
            return
        now_wall = time.perf_counter()
        now_process = time.process_time()
        elapsed = now_wall - self._cpu_last_wall
        if elapsed > 0:
            self._cpu_percent = (
                (now_process - self._cpu_last_process) / elapsed * 100.0
            )
        self._cpu_last_wall = now_wall
        self._cpu_last_process = now_process
        self._update_advanced_monitor_values()
        self._monitor_after_id = self.after(
            1000, self._update_advanced_monitor
        )

    def _update_plan_display(self) -> None:
        plan = "PRO" if self.VIP else "FREE"
        self.title(f"Free2Play — {plan}")
        if hasattr(self, "plan_label"):
            self.plan_label.configure(text=f"Plan actual: {plan}")

    def _save_vip_setting(self) -> None:
        previous_value = self.VIP
        self.VIP = bool(self.vip_switch.get())
        try:
            self.settings_store.save_vip(self.VIP)
        except (OSError, ValueError) as exc:
            self.VIP = previous_value
            if previous_value:
                self.vip_switch.select()
            else:
                self.vip_switch.deselect()
            self.vip_config_status.configure(
                text=f"No se pudo guardar el ajuste VIP: {exc}"
            )
            self._log("Configuración", "No se pudo guardar VIP", detail=str(exc))
            return
        self.vip_config_status.configure(
            text="El valor se guarda cifrado para este usuario de Windows."
        )
        self._update_plan_display()
        self._log(
            "Configuración",
            f"Plan cambiado a {'PRO' if self.VIP else 'FREE'}",
        )

    def _set_tiktok_state(self, state: str, detail: str | None = None) -> None:
        self.tiktok_state = state
        labels = {
            "disconnected": "Desconectado",
            "connecting": "Conectando…",
            "connected": "Conectado al LIVE",
            "error": detail or "Error al conectar. Puedes reintentar manualmente.",
        }
        text = detail or labels.get(state, state)
        for label in (
            self.status_labels["tiktok"],
            self.tiktok_page_status,
        ):
            label.configure(text=text)
        button_text = (
            "Desconectar"
            if state == "connected"
            else "Conectando…" if state == "connecting"
            else "Reintentar manualmente" if state == "error"
            else "Conectar"
        )
        self.home_tiktok_button.configure(
            text=button_text,
            state="disabled" if state == "connecting" else "normal",
        )
        self.tiktok_page_button.configure(
            text=button_text,
            state="disabled" if state == "connecting" else "normal",
        )

    def _set_minecraft_state(self, state: str, detail: str | None = None) -> None:
        self.minecraft_state = state
        labels = {
            "disconnected": "Desconectado",
            "connecting": "Comprobando API Bridge…",
            "connected": "Conectado a API Bridge",
            "error": "Error de conexión",
        }
        self.status_labels["minecraft"].configure(
            text=detail or labels.get(state, state)
        )

    def _set_automation_state(self) -> None:
        text = "Activa" if self.automation_running else "Pausada"
        self.status_labels["automation"].configure(text=text)
        self.home_automation_button.configure(
            text=(
                "Pausar automatización"
                if self.automation_running
                else "Iniciar automatización"
            )
        )

    def _log(
        self,
        event_type: str,
        result: str,
        *,
        rule_name: str = "",
        detail: str = "",
    ) -> None:
        self.ui_queue.put(
            (
                "log",
                (event_type, rule_name, result, detail),
            )
        )

    def _write_log(
        self, event_type: str, rule_name: str, result: str, detail: str
    ) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_values = [event_type, rule_name, result, detail]
        if self.api_token:
            safe_values = [value.replace(self.api_token, "[token oculto]") for value in safe_values]
        row = (timestamp, *safe_values)
        self.log_rows.append(row)
        del self.log_rows[:-300]
        line = (
            f"{timestamp} | {row[1]} | {row[2] or '-'} | {row[3]} | {row[4]}\n"
        )
        for textbox in (
            getattr(self, "log_textbox", None),
            getattr(self, "recent_activity", None),
            getattr(self, "advanced_log_textbox", None),
        ):
            if textbox is None:
                continue
            textbox.configure(state="normal")
            textbox.insert("end", line)
            textbox.see("end")
            textbox.configure(state="disabled")
        self.current_activity = f"{result}: {detail or event_type}"
        self._update_advanced_monitor_values()

    def _submit(
        self,
        action: str,
        function: Callable[[], Any],
        metadata: Any = None,
    ) -> Future[Any]:
        future = self.executor.submit(function)

        def completed(task: Future[Any]) -> None:
            try:
                result = task.result()
                payload = (action, metadata, result, None)
            except Exception as exc:
                payload = (action, metadata, None, str(exc))
            self.ui_queue.put(("task_result", payload))

        future.add_done_callback(completed)
        return future

    def _process_queue(self) -> None:
        self._queue_after_id = None
        if self._closing:
            return
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "log":
                    self._write_log(*payload)
                elif kind == "tiktok_process":
                    generation, process = payload
                    if generation == self.tiktok_generation:
                        self.tiktok_process = process
                elif kind == "tiktok_event":
                    generation, raw_event = payload
                    if generation == self.tiktok_generation:
                        self._handle_tiktok_event(raw_event)
                elif kind == "tiktok_finished":
                    generation, error = payload
                    if generation == self.tiktok_generation:
                        self.tiktok_process = None
                        stop_requested = self.tiktok_stop_requested
                        self.tiktok_stop_requested = False
                        if stop_requested:
                            self._set_tiktok_state("disconnected")
                            self._log("TikTok", "Desconectado")
                        else:
                            failure = error or (
                                "el proceso terminó antes de confirmar "
                                "la conexión al LIVE"
                                if not self.tiktok_connected_for_generation
                                else "el proceso de conexión terminó"
                            )
                            message = (
                                "Error al conectar. Revisa el nombre de usuario, "
                                "que la cuenta esté en LIVE y tu conexión. "
                                "Puedes reintentar manualmente."
                            )
                            self._set_tiktok_state("error", message)
                            self.current_activity = "TikTok: error al conectar"
                            self._log(
                                "TikTok",
                                "Error al conectar",
                                detail=f"{failure}. Reintento manual disponible.",
                            )
                elif kind == "task_result":
                    self._handle_task_result(*payload)
            except Exception as exc:
                self._write_log("Aplicación", "", "Error al procesar evento", str(exc))
        self._queue_after_id = self.after(100, self._process_queue)

    def _handle_tiktok_event(self, raw_event: str) -> None:
        try:
            event = json.loads(raw_event)
        except json.JSONDecodeError as exc:
            self._log("TikTok", "Evento JSON no válido", detail=str(exc))
            return
        if not isinstance(event, dict):
            self._log("TikTok", "Evento JSON con formato no válido")
            return
        event_type = str(event.get("event", "unknown"))
        if event_type == "gift_catalog":
            catalog = event.get("gifts")
            if not isinstance(catalog, list):
                self._log(
                    "TikTok",
                    "Catálogo de regalos con formato no válido",
                )
                return
            names: list[str] = []
            seen_names: set[str] = set()
            for item in catalog:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                cleaned_name = name.strip()
                if cleaned_name.casefold() not in seen_names:
                    names.append(cleaned_name)
                    seen_names.add(cleaned_name.casefold())
            self.gift_catalog_names = names
            self._log(
                "TikTok",
                "Catálogo de regalos cargado" if names else "Catálogo vacío",
                detail=(
                    f"{len(names)} regalos disponibles para seleccionar."
                    if names
                    else "Puedes escribir el nombre del regalo manualmente."
                ),
            )
            return
        if event_type == "gift_catalog_error":
            self._log(
                "TikTok",
                "No se pudo cargar el catálogo de regalos",
                detail=str(event.get("message") or "Puedes escribir el nombre manualmente."),
            )
            return
        username = event.get("shortname") or event.get("user") or ""
        detail = str(
            event.get("text")
            or event.get("gift_name")
            or event.get("amount")
            or ""
        )
        self.events_processed += 1
        if event_type == "like":
            try:
                self.likes_received += max(0, int(event.get("count") or 0))
            except (TypeError, ValueError):
                self._log(
                    "TikTok",
                    "Evento de likes con count no válido",
                    detail=str(event.get("count")),
                )
        self.last_event_description = (
            f"{EVENT_LABELS.get(event_type, event_type)}"
            + (f" — {username}" if username else "")
            + (f" — {detail}" if detail else "")
        )
        self.current_activity = f"Procesando evento: {self.last_event_description}"
        self._update_advanced_monitor_values()
        if event_type == "connect":
            self.gift_catalog_names = []
            self.forwarded_comment_ids.clear()
            self.forwarded_comment_order.clear()
            self.tiktok_connected_for_generation = True
            self.rule_engine.reset_like_progress()
            self._set_tiktok_state("connected")
            self._log("TikTok", "Conectado al LIVE", detail=str(event.get("room_id") or ""))
        elif event_type == "disconnect":
            self._set_tiktok_state("disconnected")
            self._log("TikTok", "Desconectado del LIVE")
        elif event_type == "live_end":
            self._set_tiktok_state("connected", "LIVE finalizado; cerrando conexión…")
            self._log("TikTok", "LIVE finalizado")
        else:
            self._log(event_type, "Recibido", detail=" — ".join(filter(None, (username, detail))))

        missing_fields = missing_event_fields(event)
        if missing_fields:
            self._log(
                event_type,
                "Evento incompleto; no se evaluaron reglas",
                detail="Faltan campos: " + ", ".join(missing_fields),
            )
            return
        if event_type == "gift":
            try:
                if int(event.get("amount", 0)) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                self._log(
                    event_type,
                    "Cantidad de regalo no válida; no se evaluaron reglas",
                    detail=str(event.get("amount")),
                )
                return

        if event_type == "comment" and self.comment_chat_switch.get():
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in self.forwarded_comment_ids:
                self._log(
                    event_type,
                    "Comentario duplicado; no se volvió a enviar",
                    detail=event_id,
                )
            else:
                if event_id:
                    if len(self.forwarded_comment_order) == (
                        self.forwarded_comment_order.maxlen
                    ):
                        oldest = self.forwarded_comment_order[0]
                        self.forwarded_comment_ids.discard(oldest)
                    self.forwarded_comment_order.append(event_id)
                    self.forwarded_comment_ids.add(event_id)
                self._send_comment_to_minecraft(event)

        if not self.automation_running:
            return
        fallback_rule = None
        if (
            event_type == "gift"
            and self.unmatched_gift_fallback_switch.get()
        ):
            try:
                fallback_rule = Rule.create(
                    "Regalo sin regla (acción alternativa)",
                    "gift",
                    {},
                    (
                        self.unmatched_gift_command_entry.get().strip()
                        or DEFAULT_UNMATCHED_GIFT_COMMAND
                    ),
                )
            except ValueError as exc:
                self._log(
                    event_type,
                    "Acción alternativa no válida",
                    detail=str(exc),
                )
        for rule in self.rule_engine.match_event(
            event, fallback_rule=fallback_rule
        ):
            self._log(event_type, "Regla activada", rule_name=rule.name)
            if self.minecraft_state != "connected" or not self.api_token:
                self._log(
                    event_type,
                    "No ejecutada: Minecraft desconectado",
                    rule_name=rule.name,
                )
                continue
            repeat_cycles = 1
            if rule.action_kind == "spawn":
                if event_type == "like":
                    try:
                        like_increment = max(0, int(event.get("count") or 0))
                    except (TypeError, ValueError):
                        like_increment = 0
                    thresholds = self.rule_engine.consume_likes(
                        rule, like_increment
                    )
                    if thresholds == 0:
                        self._log(
                            event_type,
                            "Esperando el siguiente umbral de likes",
                            rule_name=rule.name,
                            detail=(
                                f"{like_increment} likes recibidos; "
                                f"umbral {rule.like_threshold}"
                            ),
                        )
                        continue
                    repeat_cycles = thresholds * rule.spawn_count
                else:
                    repeat_cycles = rule.spawn_count
            else:
                repeat_cycles = rule.repeat_count
            if rule.repeat_by_amount and event_type == "gift":
                try:
                    gift_units = max(1, int(event.get("amount") or 1))
                except (TypeError, ValueError):
                    gift_units = 1
                    self._log(
                        event_type,
                        "Cantidad del regalo no válida; se usará 1",
                        rule_name=rule.name,
                        detail=str(event.get("amount")),
                    )
                repeat_cycles *= gift_units

            token = self.api_token
            base_url = self.api_url_entry.get().strip()
            event_values = dict(event)
            event_values["entity"] = rule.entity_id
            event_values["player"] = (
                self.minecraft_target_entry.get().strip() or "@a"
            )
            try:
                action_commands = render_action_commands(
                    rule.action, event_values
                )
            except ValueError as exc:
                self._log(
                    event_type,
                    "No se pudo preparar la acción",
                    rule_name=rule.name,
                    detail=str(exc),
                )
                continue
            if not action_commands:
                self._log(
                    event_type,
                    "La acción no contiene comandos",
                    rule_name=rule.name,
                )
                continue
            if repeat_cycles <= 0:
                self._log(
                    event_type,
                    "No hay unidades para procesar",
                    rule_name=rule.name,
                )
                continue

            announcement_commands: list[str] = []
            if self.rule_announcement_switch.get():
                event_values["regla"] = rule.name
                event_values["evento"] = EVENT_LABELS.get(
                    event_type, event_type
                )
                event_values["interaccion"] = self._interaction_description(
                    event
                )
                try:
                    announcement_commands.append(
                        render_tellraw_command(
                            "@a",
                            (
                                self.rule_announcement_template_entry.get().strip()
                                or DEFAULT_RULE_ANNOUNCEMENT_TEMPLATE
                            ),
                            event_values,
                            color=self.rule_announcement_color_menu.get(),
                        )
                    )
                except ValueError as exc:
                    self._log(
                        event_type,
                        "No se pudo preparar el anuncio de chat",
                        rule_name=rule.name,
                        detail=str(exc),
                    )

            requested_commands = (
                len(action_commands) * repeat_cycles
                + len(announcement_commands)
            )
            if requested_commands > 64:
                self._log(
                    event_type,
                    "Se limitó la cantidad de comandos por evento",
                    rule_name=rule.name,
                    detail=(
                        f"Se solicitaron {requested_commands} comandos; "
                        "máximo por evento: 64."
                    ),
                )
            action_capacity = 64 - len(announcement_commands)
            command_sequence = announcement_commands + (
                action_commands[:action_capacity]
                * min(repeat_cycles, action_capacity)
            )[:action_capacity]
            debug_enabled = bool(self.debug_commands_switch.get())
            if debug_enabled:
                self._log(
                    event_type,
                    "Solicitando comandos a API Bridge",
                    rule_name=rule.name,
                    detail="\n".join(command_sequence),
                )
            self.current_activity = (
                f"Enviando {len(command_sequence)} comando(s) de «{rule.name}»"
            )
            self._update_advanced_monitor_values()
            self._submit(
                "minecraft_command",
                lambda commands=command_sequence, auth=token, url=base_url: (
                    execute_command_sequence(auth, commands, url)
                ),
                metadata=(
                    rule.name,
                    event_type,
                    command_sequence,
                    debug_enabled,
                ),
            )

    @staticmethod
    def _interaction_description(event: dict[str, Any]) -> str:
        event_type = str(event.get("event", ""))
        if event_type == "gift":
            return (
                f"envió {event.get('gift_name') or 'un regalo'} "
                f"x{event.get('amount') or 1}"
            )
        if event_type == "comment":
            return f"comentó: {event.get('text') or ''}"
        if event_type == "like":
            return f"dio {event.get('count') or 0} likes"
        if event_type == "follow":
            return "empezó a seguir el LIVE"
        if event_type == "share":
            return "compartió el LIVE"
        if event_type == "join":
            return "entró al LIVE"
        return EVENT_LABELS.get(event_type, event_type)

    def _send_comment_to_minecraft(self, event: dict[str, Any]) -> None:
        if self.minecraft_state != "connected" or not self.api_token:
            self._log(
                "comment",
                "Comentario no enviado: Minecraft desconectado",
            )
            return
        event_values = dict(event)
        event_values["username"] = (
            event.get("user") or event.get("shortname") or "TikTok"
        )
        try:
            command = render_tellraw_command(
                "@a",
                (
                    self.comment_chat_template_entry.get().strip()
                    or DEFAULT_COMMENT_CHAT_TEMPLATE
                ),
                event_values,
                color="light_purple",
            )
        except ValueError as exc:
            self._log(
                "comment",
                "No se pudo preparar el comentario para Minecraft",
                detail=str(exc),
            )
            return

        debug_enabled = bool(self.debug_commands_switch.get())
        self.current_activity = "Enviando comentario de TikTok al chat"
        self._update_advanced_monitor_values()
        self._submit(
            "minecraft_command",
            lambda auth=self.api_token, url=self.api_url_entry.get().strip(), msg=command: (
                execute_command_sequence(auth, [msg], url)
            ),
            metadata=(
                "Chat de comentario TikTok",
                "comment",
                [command],
                debug_enabled,
            ),
        )

    def _handle_task_result(
        self,
        action: str,
        metadata: Any,
        result: Any,
        error: str | None,
    ) -> None:
        if action == "minecraft_install":
            self.install_button.configure(state="normal")
            if error:
                self.install_status.configure(text="Falló la instalación.")
                self._log("Minecraft", "Instalación fallida", detail=error)
            else:
                self.install_status.configure(text="Instalación completada.")
                self._log("Minecraft", "API Bridge instalado", detail=result)
            return

        if action == "token_read":
            self.get_token_button.configure(state="normal")
            if error:
                self.token_status.configure(text="Token: no encontrado")
                self._log("Minecraft", "No se pudo leer el token", detail=error)
            else:
                self.api_token, log_path = result
                self.token_status.configure(text="Token: cargado en memoria (oculto)")
                self._log(
                    "Minecraft",
                    "Token leído; valor oculto",
                    detail=str(log_path),
                )
            return

        if action in {"minecraft_connect", "minecraft_test"}:
            self._minecraft_check_in_progress = False
            if error:
                self.api_token = None
                self.token_status.configure(text="Token: no cargado")
                self._set_minecraft_state("error", "Error al probar API Bridge")
                self._log("Minecraft", "Prueba de conexión fallida", detail=error)
            else:
                self.api_token = result[0]
                response = result[1]
                self._set_minecraft_state("connected")
                self.token_status.configure(text="Token: cargado en memoria (oculto)")
                self._log(
                    "Minecraft",
                    f"Conexión HTTP correcta (HTTP {response.status})",
                    detail=(
                        "GET /api/"
                        + (
                            f"\nRespuesta: {response.body}"
                            if self.debug_commands_switch.get()
                            else ""
                        )
                    ),
                )
            return

        if action == "minecraft_command":
            rule_name, event_type, commands, debug_enabled = metadata
            if error:
                self.current_activity = (
                    f"Falló la secuencia de «{rule_name}»: {error}"
                )
                self._log(
                    event_type,
                    "Falló la solicitud de comandos",
                    rule_name=rule_name,
                    detail=(
                        f"{'; '.join(commands)} — {error}"
                        if debug_enabled
                        else error
                    ),
                )
            else:
                outcomes: list[CommandExecution] = result
                accepted = 0
                for outcome in outcomes:
                    if outcome.response is None:
                        self._log(
                            event_type,
                            "API Bridge rechazó el comando",
                            rule_name=rule_name,
                            detail=(
                                f"Comando: {outcome.command}\n"
                                f"Error HTTP {outcome.error_status}: {outcome.error}\n"
                                f"Respuesta: {outcome.error_body}"
                                if debug_enabled
                                else outcome.error or "Error sin detalle"
                            ),
                        )
                        continue
                    accepted += 1
                    response = outcome.response
                    self.commands_sent += 1
                    try:
                        body = json.loads(response.body)
                    except json.JSONDecodeError:
                        body = None
                    message = (
                        str(body.get("message", ""))
                        if isinstance(body, dict)
                        else ""
                    )
                    if isinstance(body, dict) and body.get("success") is True:
                        if message.startswith("Command queued:"):
                            status_text = (
                                f"API Bridge encoló el comando (HTTP {response.status})"
                            )
                        else:
                            status_text = (
                                f"API Bridge aceptó la solicitud (HTTP {response.status}); "
                                "ejecución no confirmada"
                            )
                    else:
                        status_text = (
                            f"Respuesta HTTP {response.status}; "
                            "ejecución no confirmada"
                        )
                    detail = (
                        f"Comando: {outcome.command}\nRespuesta: {response.body}"
                        if debug_enabled
                        else ""
                    )
                    self._log(
                        event_type,
                        status_text,
                        rule_name=rule_name,
                        detail=detail,
                    )
                self.current_activity = (
                    f"API Bridge aceptó {accepted}/{len(outcomes)} comando(s) "
                    f"de «{rule_name}»; revisa el log del juego para confirmar "
                    "su ejecución."
                )
            self._update_advanced_monitor_values()

    def _toggle_tiktok(self) -> None:
        if self.tiktok_state == "connected":
            self._disconnect_tiktok()
        elif self.tiktok_state in {"disconnected", "error"}:
            self._connect_tiktok()

    def _connect_tiktok(self) -> None:
        if self.tiktok_thread is not None and self.tiktok_thread.is_alive():
            self._log("TikTok", "Ya hay una conexión activa o finalizando")
            return
        username = self.tiktok_username_entry.get().strip()
        if not username:
            messagebox.showwarning(
                "Falta el usuario",
                "Escribe el nombre de usuario de TikTok.",
                parent=self,
            )
            self._show_page("TikTok LIVE")
            return
        self._save_user_preferences()
        self.tiktok_generation += 1
        generation = self.tiktok_generation
        self.tiktok_stop_requested = False
        self.tiktok_connected_for_generation = False
        self.current_activity = f"Intentando conectar TikTok: {username.lstrip('@')}"
        self._set_tiktok_state("connecting")
        self._log("TikTok", "Iniciando conexión", detail=username.lstrip("@"))

        def run_cli() -> None:
            error: str | None = None
            stderr_lines: deque[str] = deque(maxlen=30)
            stderr_thread: threading.Thread | None = None
            process: subprocess.Popen[str] | None = None
            try:
                process = subprocess.Popen(
                    tiktok_command(username),
                    cwd=APP_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0
                    ),
                )
                self.ui_queue.put(("tiktok_process", (generation, process)))

                def drain_stderr() -> None:
                    if process.stderr is None:
                        return
                    for line in process.stderr:
                        message = line.strip()
                        if message:
                            stderr_lines.append(message)

                stderr_thread = threading.Thread(
                    target=drain_stderr,
                    name="TikTokCliStderr",
                    daemon=True,
                )
                stderr_thread.start()

                if process.stdout is None:
                    raise RuntimeError("El CLI de TikTok no abrió su salida JSON.")
                for line in process.stdout:
                    if line.strip():
                        self.ui_queue.put(
                            ("tiktok_event", (generation, line.strip()))
                        )
                return_code = process.wait()
                if stderr_thread is not None:
                    stderr_thread.join(timeout=1)
                if return_code and not self.tiktok_stop_requested:
                    error = (
                        "\n".join(stderr_lines)
                        or f"El CLI de TikTok terminó con código {return_code}."
                    )
            except Exception as exc:
                error = str(exc)
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                self.ui_queue.put(("tiktok_finished", (generation, error)))

        self.tiktok_thread = threading.Thread(
            target=run_cli,
            name="TikTokLiveCli",
            daemon=True,
        )
        self.tiktok_thread.start()

    def _disconnect_tiktok(self) -> None:
        process = self.tiktok_process
        if process is None or process.poll() is not None:
            self._log("TikTok", "El proceso CLI ya no está activo")
            return
        self.tiktok_stop_requested = True
        try:
            process.terminate()
        except OSError as exc:
            self._log("TikTok", "No se pudo detener el CLI", detail=str(exc))
            self.tiktok_stop_requested = False
            return
        self._set_tiktok_state("connecting", "Desconectando…")
        self._log("TikTok", "Solicitud para detener el proceso CLI enviada")

    def _toggle_automation(self) -> None:
        if (
            not self.automation_running
            and self.active_profile_name.casefold() == "dani"
            and not messagebox.askyesno(
                "Activar el perfil Dani",
                "Este perfil puede invocar mobs hostiles, creepers, TNT, rayos, "
                "wardens, withers y dragones, además de teletransportar jugadores. "
                "Pruébalo primero en un mundo seguro. ¿Activar la automatización?",
                parent=self,
            )
        ):
            return
        self.automation_running = not self.automation_running
        self._set_automation_state()
        self._log(
            "Automatización",
            "Iniciada" if self.automation_running else "Pausada",
        )

    def _browse_instance(self) -> None:
        selected = filedialog.askdirectory(
            title="Selecciona la carpeta de la instancia de Minecraft"
        )
        if selected:
            self.instance_dir = Path(selected)
            self.instance_path_entry.delete(0, "end")
            self.instance_path_entry.insert(0, selected)
            self._save_user_preferences()

    def _selected_instance(self) -> Path | None:
        raw = self.instance_path_entry.get().strip()
        if raw:
            return Path(raw).expanduser()
        return self.instance_dir

    def _selected_log_path(self) -> Path:
        instance = self._selected_instance()
        if instance is not None:
            return instance / "logs" / "latest.log"
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise FileNotFoundError(
                "Selecciona la carpeta de la instancia de Minecraft."
            )
        return Path(appdata) / ".minecraft" / "logs" / "latest.log"

    def _read_token(self) -> tuple[str, Path]:
        log_path = self._selected_log_path()
        token = find_api_bridge_token(log_path)
        if token is None:
            raise RuntimeError(
                f"No se encontró un token válido en {log_path}. "
                "Comprueba que API Bridge se haya iniciado."
            )
        return token, log_path

    def _get_token(self) -> None:
        self.get_token_button.configure(state="disabled")

        def work() -> tuple[str, Path]:
            return self._read_token()

        self._submit("token_read", work)

    def _connect_minecraft(self) -> None:
        if self._minecraft_check_in_progress:
            return
        self._minecraft_check_in_progress = True
        self._set_minecraft_state("connecting")
        self._log("Minecraft", "Comprobando conexión con API Bridge")
        base_url = self.api_url_entry.get().strip()

        def work() -> tuple[str, Any]:
            token, log_path = self._read_token()
            response = test_connection(token, base_url)
            self._log(
                "Minecraft",
                "Token leído; valor oculto",
                detail=str(log_path),
            )
            return token, response

        self._submit("minecraft_connect", work)

    def _test_minecraft_connection(self) -> None:
        if self._minecraft_check_in_progress:
            return
        self._minecraft_check_in_progress = True
        self._set_minecraft_state("connecting", "Probando API Bridge…")
        base_url = self.api_url_entry.get().strip()

        def work() -> tuple[str, Any]:
            token = self.api_token
            if token is None:
                token, log_path = self._read_token()
                self._log(
                    "Minecraft",
                    "Token leído; valor oculto",
                    detail=str(log_path),
                )
            return token, test_connection(token, base_url)

        self._submit("minecraft_test", work)

    def _install_mod(self) -> None:
        instance = self._selected_instance()
        version = self.minecraft_version_combo.get().strip()
        loader = self.loader_menu.get().strip()
        if instance is None:
            messagebox.showwarning(
                "Instancia requerida",
                "Selecciona la carpeta de la instancia.",
                parent=self,
            )
            return
        if not version:
            messagebox.showwarning(
                "Versión requerida",
                "Selecciona o escribe una versión compatible de Minecraft.",
                parent=self,
            )
            return
        force = bool(self.install_force_switch.get())
        if force and not messagebox.askyesno(
            "Confirmar reemplazo",
            "Si ya existe un JAR de API Bridge con contenido distinto, se reemplazará "
            "después de verificar la nueva descarga. ¿Continuar?",
            parent=self,
        ):
            return

        self._save_user_preferences()
        self.install_button.configure(state="disabled")
        self.install_status.configure(text="Descargando y verificando en segundo plano…")
        def install_cli() -> str:
            completed = subprocess.run(
                api_bridge_install_command(
                    version,
                    loader,
                    instance / "mods",
                    force=force,
                ),
                cwd=APP_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
            output = "\n".join(
                part.strip()
                for part in (completed.stdout, completed.stderr)
                if part and part.strip()
            )
            if completed.returncode:
                raise RuntimeError(
                    output
                    or "El instalador CLI terminó con código "
                    f"{completed.returncode}."
                )
            return output or "El instalador terminó correctamente."

        self._submit("minecraft_install", install_cli)

    def _load_rules(self) -> None:
        try:
            legacy_rules = self.rule_store.load()
            self.profiles = self.profile_store.load(legacy_rules)
        except (OSError, ValueError) as exc:
            self.profiles = [RuleProfile("dani", [])]
            self._log("Perfiles", "No se pudieron cargar", detail=str(exc))
        preferred_name = str(
            self.preferences.get("active_profile", "dani")
        ).casefold()
        selected_profile = next(
            (
                profile
                for profile in self.profiles
                if profile.name.casefold() == preferred_name
            ),
            None,
        )
        if selected_profile is None:
            selected_profile = next(
                (
                    profile
                    for profile in self.profiles
                    if profile.name.casefold() == "dani"
                ),
                self.profiles[0],
            )
        self.active_profile_name = selected_profile.name
        self.rules = selected_profile.rules
        self.profile_menu.configure(
            values=[profile.name for profile in self.profiles]
        )
        self.profile_menu.set(self.active_profile_name)
        self.profile_status.configure(
            text=(
                f"Perfil «{self.active_profile_name}»: {len(self.rules)} reglas. "
                "Los comandos de entidades hostiles, rayos, teletransporte y TNT "
                "pueden afectar al mundo; prueba en una instancia segura."
            )
        )
        self.rule_engine.rules = self.rules
        self._refresh_rules_list()

    def _save_rules(self) -> bool:
        profile = self._active_profile()
        previous_rules = profile.rules
        profile.rules = self.rules
        try:
            self.profile_store.save(self.profiles)
        except (OSError, ValueError) as exc:
            profile.rules = previous_rules
            messagebox.showerror(
                "Error al guardar perfil", str(exc), parent=self
            )
            self._log("Perfiles", "Error al guardar", detail=str(exc))
            return False
        self.rule_engine.rules = self.rules
        self._refresh_rules_list()
        self.profile_status.configure(
            text=f"Perfil «{self.active_profile_name}»: {len(self.rules)} reglas."
        )
        self._log(
            "Perfiles",
            "Reglas guardadas",
            detail=f"{self.active_profile_name}: {len(self.rules)} regla(s)",
        )
        return True

    def _active_profile(self) -> RuleProfile:
        profile = next(
            (
                item
                for item in self.profiles
                if item.name == self.active_profile_name
            ),
            None,
        )
        if profile is None:
            raise ValueError("El perfil activo ya no existe.")
        return profile

    def _switch_profile(self, profile_name: str) -> None:
        if profile_name == self.active_profile_name:
            return
        current = self._active_profile()
        current.rules = self.rules
        profile = next(
            (item for item in self.profiles if item.name == profile_name),
            None,
        )
        if profile is None:
            self._log("Perfiles", "Perfil no encontrado", detail=profile_name)
            return
        self.active_profile_name = profile.name
        self.rules = profile.rules
        self.selected_rule_id = None
        self.rule_engine.rules = self.rules
        self.rule_engine.reset_like_progress()
        try:
            self.profile_store.save(self.profiles)
        except (OSError, ValueError) as exc:
            self._log("Perfiles", "No se pudo guardar el cambio", detail=str(exc))
        self.preferences["active_profile"] = self.active_profile_name
        self._save_user_preferences()
        self._refresh_rules_list()
        self.profile_status.configure(
            text=f"Perfil «{self.active_profile_name}»: {len(self.rules)} reglas."
        )
        self._log("Perfiles", "Perfil activado", detail=self.active_profile_name)

    def _create_profile(self) -> None:
        dialog = ctk.CTkInputDialog(
            text="Nombre del perfil nuevo (se copiarán las reglas actuales):",
            title="Crear perfil",
        )
        profile_name = (dialog.get_input() or "").strip()
        if not profile_name:
            return
        if any(
            profile.name.casefold() == profile_name.casefold()
            for profile in self.profiles
        ):
            messagebox.showerror(
                "Perfil existente",
                "Ya existe un perfil con ese nombre.",
                parent=self,
            )
            return
        copied_rules = [
            Rule.from_dict(asdict(rule))
            for rule in self.rules
        ]
        profile = RuleProfile(profile_name, copied_rules)
        self.profiles.append(profile)
        try:
            self.profile_store.save(self.profiles)
        except (OSError, ValueError) as exc:
            self.profiles.pop()
            messagebox.showerror("No se pudo crear el perfil", str(exc), parent=self)
            self._log("Perfiles", "Error al crear", detail=str(exc))
            return
        self.profile_menu.configure(
            values=[item.name for item in self.profiles]
        )
        self.profile_menu.set(profile_name)
        self._switch_profile(profile_name)

    def _refresh_rules_list(self) -> None:
        if not hasattr(self, "rules_list"):
            return
        for child in self.rules_list.winfo_children():
            child.destroy()
        for row, rule in enumerate(self.rules):
            description = (
                f"{rule.name}  |  "
                f"{EVENT_LABELS.get(rule.event_type, rule.event_type)}  |  "
                f"{'Activa' if rule.enabled else 'Pausada'}  |  "
                f"{rule.action}"
            )
            button = ctk.CTkButton(
                self.rules_list,
                text=description,
                anchor="w",
                fg_color=(
                    ("#cfe8ff", "#1f538d")
                    if rule.id == self.selected_rule_id
                    else ("#e5e5e5", "#343638")
                ),
                text_color=("black", "white"),
                command=lambda selected_id=rule.id: self._select_rule(selected_id),
            )
            button.grid(row=row, column=0, padx=4, pady=4, sticky="ew")
        self.rules_list.grid_columnconfigure(0, weight=1)

    def _select_rule(self, rule_id: str) -> None:
        self.selected_rule_id = rule_id
        self._refresh_rules_list()

    def _selected_rule(self) -> Rule | None:
        return next(
            (rule for rule in self.rules if rule.id == self.selected_rule_id),
            None,
        )

    def _create_rule(self) -> None:
        RuleDialog(self, self._upsert_rule)

    def _edit_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            messagebox.showinfo("Selecciona una regla", "Elige una regla primero.")
            return
        RuleDialog(self, self._upsert_rule, rule)

    def _upsert_rule(self, rule: Rule) -> None:
        previous_rules = self.rules.copy()
        previous_selection = self.selected_rule_id
        for index, existing in enumerate(self.rules):
            if existing.id == rule.id:
                self.rules[index] = rule
                break
        else:
            self.rules.append(rule)
        self.selected_rule_id = rule.id
        if not self._save_rules():
            self.rules = previous_rules
            self.selected_rule_id = previous_selection
            self.rule_engine.rules = self.rules
            self._refresh_rules_list()

    def _toggle_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            messagebox.showinfo("Selecciona una regla", "Elige una regla primero.")
            return
        previous_enabled = rule.enabled
        rule.enabled = not previous_enabled
        if not self._save_rules():
            rule.enabled = previous_enabled
            self.rule_engine.rules = self.rules
            self._refresh_rules_list()

    def _delete_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            messagebox.showinfo("Selecciona una regla", "Elige una regla primero.")
            return
        if not messagebox.askyesno(
            "Eliminar regla",
            f"¿Eliminar la regla «{rule.name}»?",
            parent=self,
        ):
            return
        index = self.rules.index(rule)
        self.rules.pop(index)
        self.selected_rule_id = None
        if not self._save_rules():
            self.rules.insert(index, rule)
            self.selected_rule_id = rule.id
            self.rule_engine.rules = self.rules
            self._refresh_rules_list()

    def _test_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            messagebox.showinfo("Selecciona una regla", "Elige una regla primero.")
            return
        sample_event: dict[str, Any] = {
            "event": rule.event_type,
            "userid": "test-user-id",
            "shortname": "usuario_demo",
            "user": "Usuario de prueba",
            "text": "comentario de prueba",
            "gift_name": "Regalo de prueba",
            "gift_id": "test-gift-id",
            "amount": 1,
            "count": 1,
            "total": 1,
            "diamond_count": 1,
            "repeat_count": 1,
            "entity": rule.entity_id,
            "player": (
                self.minecraft_target_entry.get().strip() or "@a"
            ),
        }
        sample_event.update(rule.conditions)
        matched = rule.matches(sample_event)
        preview = render_action_commands(rule.action, sample_event)
        preview_text = "\n".join(preview) if preview else "(sin comandos)"
        message = (
            "La regla coincide con el evento de ejemplo."
            if matched
            else "La regla está desactivada o no coincide con el evento de ejemplo."
        )
        message += (
            "\n\nVista previa (no se envía a Minecraft):\n" + preview_text
        )
        messagebox.showinfo("Prueba de regla", message, parent=self)
        self._log(
            rule.event_type,
            "Prueba correcta" if matched else "Prueba sin coincidencia",
            rule_name=rule.name,
            detail=f"Sin ejecución de comandos. Vista previa: {preview_text}",
        )

    def _on_close(self) -> None:
        self._save_user_preferences()
        self._closing = True
        for after_id in (
            self._queue_after_id,
            self._monitor_after_id,
            self._startup_connect_after_id,
        ):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except TclError:
                    pass
        self._queue_after_id = None
        self._monitor_after_id = None
        self._startup_connect_after_id = None
        process = self.tiktok_process
        if process is not None and process.poll() is None:
            process.terminate()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> None:
    worker_mode = _run_worker_if_requested()
    if worker_mode is not None:
        raise SystemExit(worker_mode)
    try:
        prepare_user_data_dir(APP_DIR, data_dir=APP_DATA_DIR)
    except OSError as exc:
        messagebox.showerror(
            "No se pudo preparar Free2Play",
            f"No se pudieron crear o migrar los datos en {APP_DATA_DIR}:\n{exc}",
        )
        raise SystemExit(1) from exc
    app = Free2PlayApp()
    app.mainloop()


def _run_worker_if_requested() -> int | None:
    """Dispatch CLI subprocess work from the bundled console executable."""
    if len(sys.argv) < 2:
        return None
    mode, *arguments = sys.argv[1:]
    if mode == "--f2p-worker-tiktok":
        from connections.tiktok import main as tiktok_main

        sys.argv = [sys.argv[0], *arguments]
        tiktok_main()
        return 0
    if mode == "--f2p-worker-api-bridge":
        from connections.APIBridge import main as api_bridge_main

        sys.argv = [sys.argv[0], *arguments]
        return api_bridge_main()
    return None


if __name__ == "__main__":
    main()
