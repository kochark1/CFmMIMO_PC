import time
import argparse
import os
from parameters.sim_params import OperatingModes

default_number_of_samples = 400000
default_number_of_samples = 100000
default_number_of_samples = 100

testing_number_of_samples = min(int(default_number_of_samples * 0.25), 1000)


# Defining some useful functions

def check_non_negative(value):
    """
    Takes a single parameter as input
    Converts it to an integer if it is a non-negative number else raises an exception.

    """

    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
    return ivalue

def check_positive(value):
    """
    Takes a single parameter as input
    Converts it to an integer if it is a non-negative number else raises an exception.

    """

    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
    return ivalue

def composite(x):
    """
    Takes a single parameter as input
    Converts it to an integer and then to a string.

    """

    return str(int(x))


# Handling comand-line arguments

parser = argparse.ArgumentParser(description='Train or test the DNN for CFmMIMO downlink power control descreibed in the paper "CNN-Based Constrained Power Control Algorithm for the Downlink of Cell-Free Massive MIMO".')
parser.add_argument('-id', '--simulationID', type=check_non_negative, help='All the logs and results folders use this id', default="0", metavar='simID', )
parser.add_argument('-s', '--samples', type=check_positive, help='Number of training samples. Takes a positive Initiger as input. Valid only for TRAINING phase.', default=default_number_of_samples, metavar='numberOfSamples', )
parser.add_argument('-m', '--mode', choices=list(map(composite, OperatingModes)), help=""" Operating mode. It takes the values from [1-4] to choose one of the following operation modes\n
    1) TRAINING           : Generates training data and performs training.\n
    2) TESTING            : Generates testing data, performs all the power control algos (trained CNN and reference algos) upon same data, and plots the results.\n
    3) PLOTTING_ONLY      : Plots the results of a test that is already done.\n
    4) ALL                : Train and then Test.\n""", default=OperatingModes.ALL, metavar='operatingMode', )
parser.add_argument('-sc', '--scenario', choices={"0", "1", "2"}, help='Takes [0-2] as input to pick one of the two scenarios described in the paper.', default="0", metavar='scenario', )
parser.add_argument('-o', '--orthogonality', choices={"0", "1"}, help='Choose 1 for orthogonal pilot and choose 0 for others.', default="0", metavar='orthogonality', )
parser.add_argument('-v', '--varK', choices={"0", "1"}, help='Choose 1 for variable K and choose 0 for others.', default="0", metavar='varK', )
parser.add_argument('-ho', '--host', choices={"0", "1"}, help='Choose 1 for triton and choose 0 for others. CHOICE 1 IS ONLY FOR THE AUTHOR OF THE CODE!', default="0", metavar='isTriton', )
parser.add_argument('-r', '--retain', choices={"0", "1"}, help='Choose 1 to retain the input data for training and choose 0 for overwritting it.', default="1", metavar='retainData', )
parser.add_argument('-c', '--clean', action='store_true', help='No arguments for this option. This option clears data logs, results, plots, models, lightning_logs and sc.pkl. Other options will be ignored.', )

args = parser.parse_args()
simulationID, number_of_samples, operating_mode, scenario, orthogonality_flag, varying_K_flag, host, retain, clean = map(int, (args.simulationID, args.samples, args.mode, args.scenario, args.orthogonality, args.varK, args.host, args.retain, args.clean ))

if clean:
    import glob, shutil
    from sys import exit
    from utils.utils import delete_folder
    training, testing, lightning = 'data_logs_training', 'data_logs_testing', 'lightning_logs'

    delete_folder(training, testing, lightning)
    
    dirs = glob.glob("simID*/")
    for dir in dirs:
        shutil.rmtree(dir, ignore_errors=False, onerror=None)

    file = 'sc.pkl'
    if os.path.isfile(file):
        os.remove(file)
        print(f'{file} removed')
    
    file = 'FCN_sc.pkl'
    if os.path.isfile(file):
        os.remove(file)
        print(f'{file} removed')

    file = 'CNN_sc.pkl'
    if os.path.isfile(file):
        os.remove(file)
        print(f'{file} removed')
    
    file = 'GFT_sc.pkl'
    if os.path.isfile(file):
        os.remove(file)
        print(f'{file} removed')

    file = 'TDN_sc.pkl'
    if os.path.isfile(file):
        os.remove(file)
        print(f'{file} removed')

    file = 'ANN_sc.pkl'
    if os.path.isfile(file):
        os.remove(file)
        print(f'{file} removed')
    
    print(f"Cleaned all! ")
    exit()


operating_mode = list(OperatingModes)[operating_mode-1]  # Translating integers to the element of OperatingModes
all_mode_flag = False
if operating_mode == OperatingModes.ALL:
    all_mode_flag = True
    operating_mode = OperatingModes.TRAINING

if not operating_mode == OperatingModes.TRAINING:
    number_of_samples = testing_number_of_samples  # Overwrites input argument 'number_of_samples' if not 'TRAINING' phase.


retain = (retain==1)  # Translating {0, 1} to {False, True}
orthogonality_flag = (orthogonality_flag == 1)
varying_K_flag = (varying_K_flag == 1)

if varying_K_flag:
    print("Varying user's feature is currently unavailable!")
    import sys
    sys.exit()


if orthogonality_flag and scenario > 1:
    print('Orthogonality flag cannot be True for these scenarios! So, it is set to False.')
    orthogonality_flag = False


print("""\nWelcome to the CFmMIMO_PC code.
Try 'python main_learn.py -h' to learn about passing optional command line arguments.\n""")


# Importing other useful libraries

from parameters.sim_params import SimulationParameters
from parameters.sys_params import SystemParameters

from generate_beta_and_pilots import data_gen

from power_control.learning import train
from power_control.testing import test_and_plot

from utils.utils import handle_deletion_and_creation


# Preparing the root directory for the logs.

cwd = os.getcwd()
if host == 1:
    # This use case is intended only for the authors of this work.
    current_folder_for_triton = cwd.split('/')[-1]
    root_base = os.path.join('/tmp', 'hsperfdata_kochark1')
    handle_deletion_and_creation(root_base, force_retain=True)

    root = os.path.join('/tmp', 'hsperfdata_kochark1', current_folder_for_triton)
    handle_deletion_and_creation(root, force_retain=True)

    triton_results_base = os.path.join('/scratch', 'work', 'kochark1', current_folder_for_triton)
    handle_deletion_and_creation(triton_results_base, force_retain=True)

else:
    root = cwd
    triton_results_base = None


# The simulation starts here.

if __name__ == '__main__':
    # Time stamp recording
    start = time.perf_counter()
    
    simulation_parameters = SimulationParameters(root, simulationID, number_of_samples, operating_mode, scenario, retain, triton_results_base, orthogonality_flag, varying_K_flag)
    
    if simulation_parameters.scenario==0:
        # coverage_area = 0.00015  # in sq.Km
        # inp_number_of_users = 5
        # inp_access_point_density = 120000
        coverage_area = 0.01  # in sq.Km
        inp_number_of_users = 4
        inp_access_point_density = 2000
        
        models_list = ['ANN',]

    elif simulation_parameters.scenario==1:
        coverage_area = 0.1  # in sq.Km
        inp_number_of_users = 20
        inp_access_point_density = 2000
        # models_list = ['TDN', 'GFT', , 'FCN', 'ANN']

        if simulation_parameters.orthogonality_flag:
            models_list = ['ANN',]
        else:
            models_list = ['ANN',]
        
    elif simulation_parameters.scenario==2:
        coverage_area = 1
        inp_number_of_users = 500
        inp_access_point_density = 2000
        models_list = ['ANN',]  # Plan is to do ['AE-FCN', 'ANN', 'GFT', 'TP']
        
    elif simulation_parameters.scenario==3:
        coverage_area = 10
        inp_number_of_users = 1000
        inp_access_point_density = 2000
        models_list = ['ANN',]  # Plan is to do ['AE-FCN', 'ANN', 'GFT', 'TP']
    
    system_parameters = SystemParameters(simulation_parameters, coverage_area, inp_number_of_users, inp_access_point_density, models_list)
    
    # Execution starts here.-----------------------------------------------------------------------------
    # Generating train & validation or test data. Do not overwrite the exiting data.
    if not os.listdir(simulation_parameters.data_folder):
        time_then = time.perf_counter()
        
        for sample_id in range(number_of_samples):
            data_gen(simulation_parameters, system_parameters, sample_id)
            if simulation_parameters.operation_mode==OperatingModes.TRAINING and sample_id < simulation_parameters.validation_number_of_data:
                data_gen(simulation_parameters, system_parameters, sample_id, validation_data=True)
        
        # Compute and display execution time.
        time_now = time.perf_counter()
        print(f'Finished data_gen in {round(time_now - time_then, 2)} second(s)')
    
    
    # Training and/or test the power control algorithms.

    if simulation_parameters.operation_mode==OperatingModes.TRAINING:
        time_then = time.perf_counter()
        
        train(simulation_parameters, system_parameters)
        
        # Compute and display execution time.
        time_now = time.perf_counter()
        print(f'Finished training in {round(time_now - time_then, 2)} second(s)')
        
        if all_mode_flag:
            operating_mode = OperatingModes.TESTING
            number_of_samples = testing_number_of_samples
            
            simulation_parameters = SimulationParameters(root, simulationID, number_of_samples, operating_mode, scenario, retain, triton_results_base, orthogonality_flag, varying_K_flag)
            system_parameters = SystemParameters(simulation_parameters, coverage_area, inp_number_of_users, inp_access_point_density, models_list)
            
            time_then = time.perf_counter()

            if not os.listdir(simulation_parameters.data_folder):
                for sample_id in range(number_of_samples):
                    data_gen(simulation_parameters, system_parameters, sample_id)
        
            test_and_plot(simulation_parameters, system_parameters, plotting_only=False)

            # Compute and display execution time.
            time_now = time.perf_counter()
            print(f'Finished dataGen, testing, and plotting in {round(time_now - time_then, 2)} second(s)')
    elif simulation_parameters.operation_mode==OperatingModes.TESTING:
        time_then = time.perf_counter()
        
        test_and_plot(simulation_parameters, system_parameters, plotting_only=False)

        # Compute and display execution time.
        time_now = time.perf_counter()
        print(f'Finished testing and plotting in {round(time_now - time_then, 2)} second(s)')

    else:  # simulation_parameters.operation_mode==OperatingModes.PLOTTING_ONLY
        test_and_plot(simulation_parameters, system_parameters, plotting_only=True)
    
    # Compute and display the execution time.
    finish = time.perf_counter()
    print(f'Finished in {round(finish - start, 2)} second(s)')