"""Interfaz gráfica sencilla para descargar videos con yt-dlp."""

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yt_dlp


def carpeta_descargas_por_defecto() -> str:
    return str(Path.home() / "Downloads")


def formatear_tiempo(segundos) -> str:
    segundos = int(segundos or 0)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def centrar(ventana, padre=None):
    """Centra la ventana sobre `padre`, o en la pantalla si no hay padre."""
    ventana.update_idletasks()
    ancho, alto = ventana.winfo_reqwidth(), ventana.winfo_reqheight()
    if padre is not None:
        x = padre.winfo_rootx() + (padre.winfo_width() - ancho) // 2
        y = padre.winfo_rooty() + (padre.winfo_height() - alto) // 2
    else:
        x = (ventana.winfo_screenwidth() - ancho) // 2
        y = (ventana.winfo_screenheight() - alto) // 3
    ventana.geometry(f"+{max(x, 0)}+{max(y, 0)}")


class LoggerSilencioso:
    """Evita que yt-dlp escriba en consola; los errores se muestran en la GUI."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


class DialogoCapitulos(tk.Toplevel):
    """Pregunta si se quiere dividir el video en capítulos, mostrando la lista."""

    def __init__(self, padre, titulo_video, capitulos):
        super().__init__(padre)
        self.withdraw()  # oculta hasta posicionarla, para que no aparezca en la esquina
        self.title("Video con capítulos")
        self.resizable(False, False)
        self.transient(padre)
        self.resultado = None  # "dividir", "completo" o None (cancelar)
        self.conservar_completo = tk.BooleanVar(value=False)

        marco = ttk.Frame(self, padding=15)
        marco.pack(fill="both", expand=True)

        ttk.Label(
            marco,
            text=f"«{titulo_video}» está dividido en {len(capitulos)} capítulos.\n"
            "¿Quieres dividirlo en un archivo por capítulo?",
            wraplength=420,
            justify="left",
        ).pack(anchor="w")

        lista_marco = ttk.Frame(marco)
        lista_marco.pack(fill="both", expand=True, pady=10)
        lista = tk.Listbox(lista_marco, height=min(len(capitulos), 10), width=60)
        barra = ttk.Scrollbar(lista_marco, orient="vertical", command=lista.yview)
        lista.configure(yscrollcommand=barra.set)
        for i, cap in enumerate(capitulos, 1):
            inicio = formatear_tiempo(cap.get("start_time"))
            lista.insert("end", f"{i:02d}. [{inicio}] {cap.get('title') or 'Sin título'}")
        lista.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        ttk.Checkbutton(
            marco,
            text="Conservar también el video completo",
            variable=self.conservar_completo,
        ).pack(anchor="w")

        botones = ttk.Frame(marco)
        botones.pack(fill="x", pady=(12, 0))
        ttk.Button(botones, text="Cancelar", command=self._cancelar).pack(side="right")
        ttk.Button(botones, text="No, video completo", command=lambda: self._elegir("completo")).pack(
            side="right", padx=5
        )
        ttk.Button(botones, text="Sí, dividir", command=lambda: self._elegir("dividir")).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        centrar(self, padre)
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def _elegir(self, opcion):
        self.resultado = opcion
        self.destroy()

    def _cancelar(self):
        self.resultado = None
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("yt-dlp GUI")
        self.minsize(560, 250)

        self.carpeta = tk.StringVar(value=carpeta_descargas_por_defecto())
        self.url = tk.StringVar()
        self.estado = tk.StringVar(value="Pega la URL de un video y pulsa Descargar.")
        self.eventos = queue.Queue()
        self.ocupado = False

        self._construir_interfaz()
        centrar(self)
        self.deiconify()
        self.after(100, self._procesar_eventos)

    # ---------- Interfaz ----------

    def _construir_interfaz(self):
        marco = ttk.Frame(self, padding=15)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(1, weight=1)

        ttk.Label(marco, text="Guardar en:").grid(row=0, column=0, sticky="w")
        ttk.Entry(marco, textvariable=self.carpeta).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(marco, text="Cambiar…", command=self._elegir_carpeta).grid(row=0, column=2)

        ttk.Label(marco, text="URL del video:").grid(row=1, column=0, sticky="w", pady=(20, 0))
        self.entrada_url = ttk.Entry(marco, textvariable=self.url, font=("Segoe UI", 11))
        self.entrada_url.grid(row=1, column=1, sticky="ew", padx=5, pady=(20, 0), ipady=4)
        self.entrada_url.bind("<Return>", lambda _e: self._iniciar())
        ttk.Button(marco, text="Pegar", command=self._pegar).grid(row=1, column=2, pady=(20, 0))

        self.boton_descargar = ttk.Button(marco, text="Descargar", command=self._iniciar)
        self.boton_descargar.grid(row=2, column=0, columnspan=3, pady=15, ipadx=20, ipady=4)

        self.progreso = ttk.Progressbar(marco, mode="determinate", maximum=100)
        self.progreso.grid(row=3, column=0, columnspan=3, sticky="ew")

        ttk.Label(marco, textvariable=self.estado, wraplength=520).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        self.boton_abrir = ttk.Button(marco, text="Abrir carpeta", command=self._abrir_carpeta)
        self.boton_abrir.grid(row=5, column=2, sticky="e", pady=(10, 0))

        self.entrada_url.focus_set()

    def _elegir_carpeta(self):
        carpeta = filedialog.askdirectory(initialdir=self.carpeta.get() or carpeta_descargas_por_defecto())
        if carpeta:
            self.carpeta.set(carpeta)

    def _pegar(self):
        try:
            self.url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def _abrir_carpeta(self):
        carpeta = self.carpeta.get()
        if os.path.isdir(carpeta):
            os.startfile(carpeta)

    def _set_ocupado(self, ocupado):
        self.ocupado = ocupado
        self.boton_descargar.configure(state="disabled" if ocupado else "normal")

    # ---------- Flujo de descarga ----------

    def _iniciar(self):
        if self.ocupado:
            return
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("Falta la URL", "Escribe o pega la URL del video.", parent=self)
            return
        carpeta = self.carpeta.get().strip()
        try:
            os.makedirs(carpeta, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Carpeta no válida", str(e), parent=self)
            return

        self._set_ocupado(True)
        self.progreso.configure(mode="indeterminate")
        self.progreso.start(12)
        self.estado.set("Obteniendo información del video…")
        threading.Thread(target=self._obtener_info, args=(url,), daemon=True).start()

    def _obtener_info(self, url):
        opciones = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": LoggerSilencioso()}
        try:
            with yt_dlp.YoutubeDL(opciones) as ydl:
                info = ydl.extract_info(url, download=False)
            self.eventos.put(("info", url, info))
        except Exception as e:
            self.eventos.put(("error", str(e)))

    def _despues_de_info(self, url, info):
        self.progreso.stop()
        self.progreso.configure(mode="determinate", value=0)

        dividir = False
        conservar_completo = True
        capitulos = info.get("chapters") or []
        if len(capitulos) > 1:
            dialogo = DialogoCapitulos(self, info.get("title", "Video"), capitulos)
            if dialogo.resultado is None:
                self.estado.set("Descarga cancelada.")
                self._set_ocupado(False)
                return
            dividir = dialogo.resultado == "dividir"
            conservar_completo = dialogo.conservar_completo.get()

        self.estado.set(f"Descargando: {info.get('title', url)}")
        threading.Thread(
            target=self._descargar,
            args=(url, self.carpeta.get().strip(), dividir, conservar_completo),
            daemon=True,
        ).start()

    def _descargar(self, url, carpeta, dividir, conservar_completo):
        opciones = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "logger": LoggerSilencioso(),
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "paths": {"home": carpeta},
            "outtmpl": {
                "default": "%(title)s.%(ext)s",
                "chapter": os.path.join("%(title)s", "%(section_number)02d - %(section_title)s.%(ext)s"),
            },
            "progress_hooks": [self._hook_progreso],
            "postprocessor_hooks": [self._hook_postproceso],
        }
        if dividir:
            opciones["postprocessors"] = [{"key": "FFmpegSplitChapters", "force_keyframes": False}]
            if not conservar_completo:
                opciones["postprocessor_hooks"].append(self._hook_borrar_completo)

        try:
            with yt_dlp.YoutubeDL(opciones) as ydl:
                ydl.download([url])
            self.eventos.put(("fin", dividir))
        except Exception as e:
            self.eventos.put(("error", str(e)))

    # Estos hooks se ejecutan en el hilo de descarga: solo envían eventos a la cola.

    def _hook_progreso(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            porcentaje = d.get("downloaded_bytes", 0) * 100 / total if total else None
            self.eventos.put(("progreso", porcentaje, d.get("_speed_str", "").strip(), d.get("_eta_str", "").strip()))
        elif d["status"] == "finished":
            self.eventos.put(("estado", "Descarga completada, procesando…"))

    def _hook_postproceso(self, d):
        if d["status"] == "started":
            nombres = {
                "Merger": "Uniendo video y audio…",
                "SplitChapters": "Dividiendo en capítulos…",
            }
            self.eventos.put(("estado", nombres.get(d["postprocessor"], "Procesando…")))

    @staticmethod
    def _hook_borrar_completo(d):
        if d["status"] == "finished" and d["postprocessor"] == "SplitChapters":
            ruta = d["info_dict"].get("filepath")
            if ruta and os.path.exists(ruta):
                os.remove(ruta)

    # ---------- Comunicación hilo -> interfaz ----------

    def _procesar_eventos(self):
        try:
            while True:
                evento = self.eventos.get_nowait()
                tipo = evento[0]
                if tipo == "info":
                    self._despues_de_info(evento[1], evento[2])
                elif tipo == "progreso":
                    _, porcentaje, velocidad, eta = evento
                    if porcentaje is not None:
                        self.progreso.configure(value=porcentaje)
                        self.estado.set(f"Descargando… {porcentaje:.1f}%  |  {velocidad}  |  quedan {eta}")
                elif tipo == "estado":
                    self.estado.set(evento[1])
                elif tipo == "fin":
                    self.progreso.configure(value=100)
                    self.estado.set("¡Listo! Capítulos guardados." if evento[1] else "¡Listo! Video guardado.")
                    self.url.set("")
                    self._set_ocupado(False)
                elif tipo == "error":
                    self.progreso.stop()
                    self.progreso.configure(mode="determinate", value=0)
                    self.estado.set("Error en la descarga.")
                    self._set_ocupado(False)
                    messagebox.showerror("Error", evento[1], parent=self)
        except queue.Empty:
            pass
        self.after(100, self._procesar_eventos)


if __name__ == "__main__":
    App().mainloop()
