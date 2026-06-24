import tkinter as tk

from video_combiner.src.ui_main import VideoCombinerApp


def main() -> None:
    root = tk.Tk()
    VideoCombinerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
