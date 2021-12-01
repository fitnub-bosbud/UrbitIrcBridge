from abc import ABC, abstractmethod

class generic_bridge(ABC):
    
    def __init__(self, instance):
        super().__init__()
        self.instance = instance
    
    """
    Start method to pass to multiprocessing
    """
    def start(self):
        pass    