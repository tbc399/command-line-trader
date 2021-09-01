import os
import yaml
import pydantic

__home_dir = os.environ['HOME']
__clt_dir = '.clt'
__clt_base_dir = os.path.join(__home_dir, __clt_dir)

if not os.path.exists(__clt_base_dir):
    os.makedirs(__clt_base_dir)

BASE_DIR = __clt_base_dir

__config_file = os.path.join(BASE_DIR, 'config.yaml')


class Config(pydantic.BaseModel):
    context: str
    

def load_config() -> Config:
    
    with open(__config_file, 'r') as file:
        try:
            config_yaml = yaml.safe_load(file)
        except yaml.YAMLError as error:
            print(error)
            
    return Config(context=config_yaml['context'])
