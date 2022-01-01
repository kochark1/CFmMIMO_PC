import sys

from setup_sim_params import get_sim_params
from channel_env.generate_beta import data_gen



def  local_execution():
    import os
    
    sim_filename = os.path.join(os.getcwd(), 'data_logs_training', 'params', 'sim_params_1.pkl')
    simulation_parameters = get_sim_params(sim_filename)
    for sample_id in range(4):
        data_gen(simulation_parameters, sample_id)

if __name__ == '__main__':
    argv = sys.argv[1:]
    if not argv:
        print("Something went wrong!")
        sys.exit()
    
    sim_filename, sample_id = argv
    simulation_parameters = get_sim_params(sim_filename)

    data_gen(simulation_parameters, sample_id)