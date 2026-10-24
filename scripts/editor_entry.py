"""Entry point for the windowed executable, including unattended failure logs."""
import sys
import traceback

from artwork_editor import main
from editor_common import settings_path


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        details = traceback.format_exc()
        log = settings_path().with_name('editor-error.log')
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(details, encoding='utf-8')
        except OSError:
            pass
        if '--self-test' not in sys.argv:
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk()
            window.withdraw()
            messagebox.showerror('OpenCabinet-BDD_Editor', 'The editor could not start.\n'+str(log), parent=window)
            window.destroy()
        if sys.stderr:
            sys.stderr.write(details)
        raise SystemExit(1)
