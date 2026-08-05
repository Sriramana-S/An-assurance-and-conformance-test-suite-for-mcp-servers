from mcp.server.fastmcp import FastMCP


mcp = FastMCP(
    "Official SDK Comparative Target",
    host="127.0.0.1",
    port=8010,
    json_response=True,
    stateless_http=True,
)


@mcp.tool(name="calculator")
def calculator(operation: str, a: float, b: float) -> float:
    """Perform a basic arithmetic operation."""
    if operation == "add":
        return a + b
    if operation == "subtract":
        return a - b
    if operation == "multiply":
        return a * b
    if operation == "divide":
        if b == 0:
            raise ValueError("Division by zero")
        return a / b
    raise ValueError(f"Unsupported operation: {operation}")


@mcp.resource("demo://status")
def status() -> str:
    """Return a simple status resource."""
    return "ok"


@mcp.prompt()
def greet(name: str) -> str:
    """Generate a friendly greeting prompt."""
    return f"Hello {name}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
