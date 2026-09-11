import json
import shutil
import subprocess
from pathlib import Path

import pytest

from monatise.application.broker_results import broker_result_status


# The same cases exercise the server and the actual pure MQL classifier,
# compiled as C++ without a terminal or broker connection.
CASES = [
    (10009, "open", "market", 42, 100, 0.1, "reconciled"),
    (10018, "open", "market", 0, 0, 0, "rejected"),
    (10019, "open", "market", 0, 0, 0, "rejected"),
    (10009, "open", "market", 0, 0, 0, "broker_uncertain"),
    (10009, "open", "market", 42, 100, 0, "broker_uncertain"),
    (10008, "open", "limit", 42, 0, 0, "reconciled"),
    (10008, "open", "stop", 42, 0, 0, "reconciled"),
    (10008, "open", "market", 42, 0, 0, "broker_uncertain"),
    (10008, "open", "limit", 0, 0, 0, "broker_uncertain"),
    (10010, "open", "market", 42, 100, 0.01, "broker_uncertain"),
    (10012, "open", "market", 0, 0, 0, "broker_uncertain"),
    (10031, "close", "", 0, 0, 0, "broker_uncertain"),
    (10009, "close", "", 0, 0, 0, "reconciled"),
    (10009, "cancel", "", 0, 0, 0, "reconciled"),
    (10025, "sl", "", 0, 0, 0, "reconciled"),
    (10025, "open", "market", 42, 100, 0.1, "broker_uncertain"),
    (99999, "open", "market", 42, 100, 0.1, "broker_uncertain"),
]


@pytest.mark.parametrize("code,operation,order_type,ticket,price,volume,expected", CASES)
def test_server_broker_evidence(code, operation, order_type, ticket, price, volume, expected):
    assert broker_result_status(operation, order_type, {
        "broker_retcode": str(code), "broker_ticket": str(ticket),
        "fill_price": str(price), "executed_volume": str(volume),
    }) == expected


def test_actual_ea_result_classifier(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    header = Path(__file__).resolve().parents[1] / "mt5/Experts/MonatiseBrokerResults.mqh"
    source = tmp_path / "broker_results.cpp"
    calls = [f'if (BrokerResultStatus({code}, {json.dumps(operation)}, {json.dumps(order_type)}, {ticket}, {price}, {volume}) != {json.dumps(expected)}) return {index + 1};'
             for index, (code, operation, order_type, ticket, price, volume, expected) in enumerate(CASES)]
    source.write_text('#include <string>\nusing string = std::string;\n' +
                      f'#include {json.dumps(str(header))}\nint main() {{\n' + '\n'.join(calls) + '\nreturn 0;}')
    executable = tmp_path / "broker_results"
    subprocess.run([compiler, "-std=c++17", str(source), "-o", str(executable)], check=True, capture_output=True)
    subprocess.run([str(executable)], check=True, capture_output=True)


def test_dashboard_failure_and_selection_regressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    test_file = Path(__file__).parent / "js/dashboard_regressions.cjs"
    result = subprocess.run([node, str(test_file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_ea_journal_lookup_reads_complete_records(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    bridge = (Path(__file__).resolve().parents[1] / "mt5/Experts/MonatiseFTMOBridge.mq5").read_text()
    lookup = bridge.split("bool JournalLookup(", 1)[1].split("\nvoid JournalAppend", 1)[0]
    source = tmp_path / "journal.cpp"
    # Model MQL CSV reads: a read consumes one field, and LineEnding becomes
    # true when the last field in that record has been consumed.
    source.write_text(r'''
#include <string>
#include <vector>
using string = std::string;
const int FILE_READ=1, FILE_CSV=2, FILE_ANSI=4, FILE_COMMON=8, INVALID_HANDLE=-1;
const string JOURNAL_FILE="test";
std::vector<std::vector<string>> rows = {
 {"first", "broker_uncertain", "", "submission began", "timestamp"},
 {"first", "reconciled", "42", "done", "timestamp"},
 {"second", "rejected", "0", "message", "with comma", "timestamp"},
 {"third", "reconciled", "43", "done", "timestamp"}
};
size_t row=0, field=0;
int FileOpen(string, int, char) { row=0; field=0; return 1; }
void FileClose(int) {}
bool FileIsEnding(int) { return row == rows.size()-1 && field == rows[row].size(); }
bool FileIsLineEnding(int) { return field == rows[row].size(); }
string FileReadString(int) {
 if (FileIsEnding(1)) return "";
 if (field == rows[row].size()) { ++row; field=0; }
 return rows[row][field++];
}
''' + "\nbool JournalLookup(" + lookup + r'''
int main() {
 string status, ticket;
 if (!JournalLookup("first", status, ticket) || status != "reconciled" || ticket != "42") return 1;
 if (!JournalLookup("second", status, ticket) || status != "rejected" || ticket != "0") return 2;
 if (!JournalLookup("third", status, ticket) || status != "reconciled" || ticket != "43") return 3;
 if (JournalLookup("missing", status, ticket)) return 4;
 return 0;
}
''')
    executable = tmp_path / "journal"
    subprocess.run([compiler, "-std=c++17", str(source), "-o", str(executable)], check=True, capture_output=True)
    subprocess.run([str(executable)], check=True, capture_output=True)
