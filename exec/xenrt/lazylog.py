import xenrt

def step(text):
    xenrt.TEC().logverbose(text, pref='STEP')

def log(text): 
    xenrt.TEC().logverbose(text)

def comment(text): 
    xenrt.TEC().comment(text)

def warning(text):
    xenrt.TEC().warning(text)
