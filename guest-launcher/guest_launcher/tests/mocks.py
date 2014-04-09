from guest_launcher import executor


class ProcessResultProvider(object):
    def __init__(self, mock_executor, args):
        self.mock_executor = mock_executor
        self.args = args
        self.process_result = None

    def then_return(self, returncode=0, stdout='', stderr=''):
        self.process_result = executor.ProcessResult(
            returncode, stdout, stderr)
        self.mock_executor.result_providers.append(self)

    def matches(self, args):
        for arg in self.args:
            if arg not in args:
                return False
        return True


class MockExecutor(object):
    def __init__(self):
        self.executed_commands = []
        self.result_providers = []

    def run(self, args):
        self.executed_commands.append(args)
        for result_provider in self.result_providers:
            if result_provider.matches(args):
                return result_provider.process_result
        return executor.ProcessResult(
            0, "", "")

    def if_found(self, *args):
        return ProcessResultProvider(self, args)
