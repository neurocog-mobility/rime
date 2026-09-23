import numpy as np
class CMFModel:
    def predict(self, inputs, params):
        active = np.asarray(inputs['input'])[:, 0] > .5
        changes = np.diff(np.r_[False, active, False].astype(int))
        return {'events': np.column_stack((np.where(changes == 1)[0], np.where(changes == -1)[0])) * 10.0}
