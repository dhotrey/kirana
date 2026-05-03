from csv import reader
from utils.config import load_config
from utils.logger import log


def read_splitwise_csv(file_path: str) -> list[list[str]]:
    with open(file_path, newline="", encoding="utf-8", mode="r") as f:
        r = reader(f)
        return [row for row in r]


def main():
    log.info("Starting Splitwise CSV import...")
    config = load_config("config.toml")
    splitwise_data = read_splitwise_csv(config.kb.splitwise_csv_path)

    header, rows = splitwise_data[0], splitwise_data[1:]
    log.debug(f"Splitwise header: {header}")
    log.debug(f"Splitwise rows: {rows[5]}")



if __name__ == "__main__":
    main()
