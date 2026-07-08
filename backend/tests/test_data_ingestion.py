import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.data_ingestion_service import DataIngestionService


class DataIngestionServiceTests(unittest.TestCase):
    def test_parse_text_rows_with_header(self):
        text = "commodity,market,price,date\nMaize,Kigali,1200,2026-07-08\n"
        rows = DataIngestionService.parse_records_from_text(text)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["commodity"], "Maize")
        self.assertEqual(rows[0]["market"], "Kigali")
        self.assertEqual(rows[0]["price"], "1200")
        self.assertEqual(rows[0]["date"], "2026-07-08")

    def test_parse_pipe_delimited_rows_without_header(self):
        text = "Beans|Muhanga|950|2026-07-07"
        rows = DataIngestionService.parse_records_from_text(text)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["commodity"], "Beans")
        self.assertEqual(rows[0]["market"], "Muhanga")
        self.assertEqual(rows[0]["price"], "950")
        self.assertEqual(rows[0]["date"], "2026-07-07")


if __name__ == "__main__":
    unittest.main()
