import customtkinter as ctk        # Import CustomTkinter for modern UI
from ui.main_window import MainWindow  # Import our main window class

# ─────────────────────────────────────────────────────────
# PRIVACYGATE — ENTRY POINT
# This is the file you run to start the app.
# It sets up the window and launches the UI.
# Run with: python main.py
# ─────────────────────────────────────────────────────────

# Set dark mode as default appearance
ctk.set_appearance_mode("dark")

# Set color theme — dark-blue gives us clean dark styling
ctk.set_default_color_theme("dark-blue")


def main():
    """Main function — creates the app window and starts it."""

    # Create the main application window
    app = ctk.CTk()

    # Set window title shown in taskbar
    app.title("PrivacyGate")

    # Set window size — width x height in pixels
    app.geometry("900x650")

    # Set minimum size — user cannot shrink below this
    app.minsize(800, 580)

    # Allow window to be resized
    app.resizable(True, True)

    # Set window background to pure black
    app.configure(fg_color="#000000")

    # Create and attach the main window UI
    window = MainWindow(app)
    window.pack(fill="both", expand=True)

    # Start the app — keeps window open and listens for events
    app.mainloop()


# Only run if this file is executed directly
# (not when imported by another file)
if __name__ == "__main__":
    main()