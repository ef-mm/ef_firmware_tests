import tkinter as tk


class TestplatzApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Testplatz")
        self.geometry("800x600")
        self.show_start_screen()

    def show_start_screen(self):
        frame = tk.Frame(self)
        frame.pack(expand=True)

        button = tk.Button(
            frame,
            text="Arbeitsplatz einrichten",
            command=self.setup_arbeitsplatz,
        )
        button.pack(padx=20, pady=20)

    def setup_arbeitsplatz(self):
        print("Arbeitsplatz einrichten wurde geklickt")


def main():
    app = TestplatzApp()
    app.mainloop()


if __name__ == "__main__":
    main()
