import torch
import torch.nn as nn
import os
import datetime
from enum import Enum, auto
from torch.utils.data import Dataset
from torch.optim.lr_scheduler import MultiStepLR, StepLR
from torch.utils.data import DataLoader
import pytorch_lightning as pl
from sys import exit
import math

from .utils import inv_sigmoid

from utils.utils import tensor_max_min_print


class Mode(Enum):
    pre_processing = auto()
    training = auto()


class RootDataset(Dataset):
    def __init__(self, data_path, phi_orth, normalizer, mode, n_samples):
        self.path = data_path
        _, _, files = next(os.walk(self.path))
        self.n_samples = min(len(list(filter(lambda k: 'betas' in k, files))), n_samples)
        self.sc = normalizer
        self.mode = mode
        self.phi_orth = phi_orth
        
    def __getitem__(self, index):
        beta_file_name = f'betas_sample{index}.pt'
        beta_file_path = os.path.join(self.path, beta_file_name)
        m = torch.load(beta_file_path)
        beta_original = m['betas'].to(dtype=torch.float32)
        pilot_sequence = m['pilot_sequence'].to(dtype=torch.int32)

        phi = torch.index_select(self.phi_orth, 0, pilot_sequence)
        phi_cross_mat = torch.abs(phi.conj() @ phi.T)
        if self.mode == Mode.pre_processing:
            beta = torch.log(beta_original.reshape((-1,)))
            return beta
        
        beta_torch = torch.log(beta_original)
        beta_torch = beta_torch.reshape((1, -1,))
        beta_torch = self.sc.transform(beta_torch)[0]
        beta_torch = torch.from_numpy(beta_torch).to(dtype=torch.float32)
        beta_torch = beta_torch.reshape(beta_original.shape)

        return phi_cross_mat, beta_torch, beta_original

    def __len__(self):
        return self.n_samples


class CommonParameters:
    n_samples = 1
    batch_size = 1

    learning_rate =1e-3
    gamma = 0.7
    step_size = 1
    num_epochs = 8
    eta = 1
    VARYING_STEP_SIZE = True

    InpDataSet = RootDataset

    @classmethod
    def pre_int(cls, simulation_parameters, system_parameters):
        cls.M = system_parameters.number_of_access_points
        cls.K = system_parameters.number_of_users

        
        cls.n_samples = simulation_parameters.number_of_samples
        cls.training_data_path = simulation_parameters.data_folder
        cls.validation_data_path = simulation_parameters.validation_data_folder
        cls.scenario = simulation_parameters.scenario
        


class RootNet(pl.LightningModule):
    def __init__(self, system_parameters, grads):
        super(RootNet, self).__init__()
        self.save_hyperparameters()
        
        self.relu = nn.ReLU()
        torch.seed()
        
        self.N = system_parameters.number_of_antennas
        self.N_inv_root = 1/math.sqrt(self.N)
        self.K_inv_root = 1/math.sqrt(system_parameters.number_of_users)
        slack_sqr = 25e-2
        slack_const = inv_sigmoid(self.K_inv_root*math.sqrt(slack_sqr))
        scale_const = inv_sigmoid(self.K_inv_root*math.sqrt((1-slack_sqr)))
        self.init_mf = self.K_inv_root*math.sqrt((1-slack_sqr))
        
        slack_variable_in = torch.ones((system_parameters.number_of_access_points, ), dtype=torch.float32)*slack_const
        # slack_variable_in = torch.tensor((slack_const,), dtype=torch.float32)
        self.register_parameter("slack_variable_in",  nn.parameter.Parameter(slack_variable_in))

        scale_factor_in = torch.ones((1, ), dtype=torch.float32)*-2.8
        self.register_parameter("scale_factor_in",  nn.parameter.Parameter(scale_factor_in))
        
        self.system_parameters = system_parameters

        self.grads = grads
        self.InpDataset = CommonParameters.InpDataSet
        self.name = None
        self.automatic_optimization = False
        
        
    def set_folder(self, model_folder):
        self.model_folder = model_folder
    
    def training_step(self, batch, batch_idx):
        opt = self.optimizers()
        phi_cross_mat, beta_torch, beta_original = batch

        opt.zero_grad()
        slack_variable = torch.nn.functional.hardsigmoid(self.slack_variable_in)*self.N_inv_root
        mus = self([beta_torch, phi_cross_mat]) # Forward pass

        with torch.no_grad():
            [mus_grads, grad_wrt_slack, utility] = self.grads(beta_original, mus, self.eta, slack_variable, self.device, self.system_parameters, phi_cross_mat)
        

        self.manual_backward(mus, None, gradient=[slack_variable, mus_grads, grad_wrt_slack])
        opt.step()
        
        with torch.no_grad():
            temp_constraints = (1 / self.system_parameters.number_of_antennas - (torch.norm(mus, dim=2)) ** 2 - slack_variable ** 2)

            if torch.any(temp_constraints<0):
                print('Training constraints failed!')
                exit()
            
            u = ((self.eta/(self.eta+1))*utility + (1/(self.eta+1))*(1/2)*(torch.log(temp_constraints).sum(dim=-1))).mean()
            # u = ((1/(self.eta+1))*(1/2)*(torch.log(temp_constraints).sum(dim=-1))).mean()
            # u = (self.eta/(self.eta+1))*utility.mean()
            # u = utility.mean()
            loss = -u # loss is negative of the utility
        
        tensorboard_logs = {'train_loss': loss}
        self.log('train_loss', loss, on_step=True, on_epoch=True, prog_bar=True)
                
        return {"loss": loss, 'log': tensorboard_logs}
    

    def validation_step(self, batch, batch_idx):
        phi_cross_mat, beta_torch, beta_original = batch

        slack_variable = torch.nn.functional.hardsigmoid(self.slack_variable_in)*self.N_inv_root
        mus = self([beta_torch, phi_cross_mat])

        [_, _, utility] = self.grads(beta_original, mus, self.eta, slack_variable, self.device, self.system_parameters, phi_cross_mat) # Replace with direct utility computation        
        
        
        temp_constraints = (1 / self.system_parameters.number_of_antennas - (torch.norm(mus, dim=2)) ** 2 - slack_variable ** 2)

        if torch.any(temp_constraints<0):
            print('Training constraints failed!')
            print('num_of_violations: ', (temp_constraints<0).sum())
            print('max_violations: ', ((torch.norm(mus, dim=2)) ** 2).max(), 'temp_constraints: ', temp_constraints)
            raise Exception("Initialization lead to power constraints violation!") 
        u = ((self.eta/(self.eta+1))*utility + (1/(self.eta+1))*(1/2)*(torch.log(temp_constraints).sum(dim=-1))).mean()
        # u = ((1/(self.eta+1))*(1/2)*(torch.log(temp_constraints).sum(dim=-1))).mean()
        # u = (self.eta/(self.eta+1))*utility.mean()
        # u = utility.mean()
        loss = -u

        self.log('val_loss', loss, on_step=True, on_epoch=True, prog_bar=True)

        return {"val_loss": loss}

    def training_epoch_end(self, outputs):
        if self.VARYING_STEP_SIZE:
            sch = self.lr_schedulers()
        if self.current_epoch % 1 == 0 and self.current_epoch>0:
            self.eta = min(self.eta*10, 1e8)
            
            if self.VARYING_STEP_SIZE and self.current_epoch < 7:
                sch.step()
        
        print(torch.nn.functional.hardsigmoid(self.scale_factor_in).item(), self.eta, self.learning_rate if not self.VARYING_STEP_SIZE else sch.get_last_lr())

        

    def backward(self, loss, *args, **kwargs):
        mus=loss

        [slack_variable, mus_grads, grad_wrt_slack_batch] = kwargs['gradient']
        B = mus_grads.shape[0]
        
        mus.backward((1/B)*mus_grads)
        for grad_wrt_slack in grad_wrt_slack_batch:
            slack_variable.backward((1/B)*grad_wrt_slack, retain_graph=True)
        # slack_variable.backward(grad_wrt_slack_batch.mean(dim=0))

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate) 
        if self.VARYING_STEP_SIZE:
            # return [optimizer], [MultiStepLR(optimizer, milestones=[32, 64, 96, 128, 160], gamma=self.gamma)]
            return [optimizer], [StepLR(optimizer, step_size=self.step_size, gamma=self.gamma)]
        else:
            return optimizer
    
    def train_dataloader(self):
        train_dataset = self.InpDataset(data_path=self.data_path, phi_orth=self.system_parameters.phi_orth, normalizer=self.normalizer, mode=Mode.training, n_samples=self.n_samples)
        train_loader = DataLoader(dataset=train_dataset, batch_size=self.batch_size, shuffle=True)
        return train_loader

    def val_dataloader(self):
        val_dataset = self.InpDataset(data_path=self.val_data_path, phi_orth=self.system_parameters.phi_orth, normalizer=self.normalizer, mode=Mode.training, n_samples=self.n_samples)
        val_loader = DataLoader(dataset=val_dataset, batch_size=self.batch_size, shuffle=False)
        return val_loader
    
    
    # def save(self):
    #     date_str = str(datetime.datetime.now().date()).replace(':', '_').replace('.', '_').replace('-', '_')
    #     time_str = str(datetime.datetime.now().time()).replace(':', '_').replace('.', '_').replace('-', '_')
    #     model_file_name = f'model_{date_str}_{time_str}.pth'

    #     model_path = os.path.join(self.model_folder, model_file_name)
    #     torch.save(self.state_dict(), model_path)
        
    #     print(model_path)
    #     print(f'{self.name} training Done!')