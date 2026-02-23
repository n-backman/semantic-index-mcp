from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common import create_minimal_swift_repo

from semantic_index.indexer import SemanticIndexer
from semantic_index.mcp_server import MCPServer


class MCPContractTests(unittest.TestCase):
    def test_initialize_list_and_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_minimal_swift_repo(root)

            SemanticIndexer(root).build_full()
            server = MCPServer(root)

            init_resp = server.handle_request(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            )
            self.assertIn("result", init_resp)
            self.assertIn("protocolVersion", init_resp["result"])

            list_resp = server.handle_request(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            tools = list_resp["result"]["tools"]
            self.assertGreaterEqual(len(tools), 6)

            call_resp = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "graph_summary", "arguments": {}},
                }
            )
            self.assertIn("result", call_resp)
            self.assertFalse(call_resp["result"]["isError"])

            find_resp = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "find_symbol",
                        "arguments": {"query": "run"},
                    },
                }
            )
            self.assertFalse(find_resp["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
