class Return(Exception):
    """
    Raised to trigger a return to the previous menu, or (if there is no
    previous menu) to exit the program.
    """
    
    pass


class ParseError(Exception):
    """
    Raised when an unresolvable issue is encountered when parsing a journal.
    """
    
    pass
