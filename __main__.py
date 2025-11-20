#__main__.py
from main import main

from c_logging import format_special


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(format_special("Exiting: Interrupted by keyboard (^C)", 'critical'))