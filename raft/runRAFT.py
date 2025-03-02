import pytest
import sys
import numpy as np
import yaml
import matplotlib.pyplot as plt

# test local code; consider src layout in future to test installed code
import raft as raft
import moorpy as mp


import importlib
mp = importlib.reload(mp)
raft = importlib.reload(raft)



def runRAFT(fname_design, fname_env):
    '''
    This the main function for running the raft model in standalone form, where inputs are contained in the specified input files.
    '''
    
    # open the design YAML file and parse it into a dictionary for passing to raft

    with open(fname_design) as file:
        design = yaml.load(file, Loader=yaml.FullLoader)
    
    print("Loading file: "+fname_design)
    print(f"'{design['name']}'")
    
    depth = float(design['mooring']['water_depth'])
    
    # now off potMod in the design dictionary to avoid BEM analysis
    for mi in design['platform']['members']:    mi['potMod'] = False

    # set up frequency range
    w = np.arange(0.05, 5, 0.05)  # frequency range (to be set by modeling options yaml)
    
    # --- Create and run the model ---

    model = raft.Model(design, w=w, depth=depth)  # set up model
    
    model.setEnv(Hs=8, Tp=12, V=10, Fthrust=float(design['turbine']['Fthrust']))  # set basic wave and wind info

    model.calcSystemProps()          # get all the setup calculations done within the model
    
    model.solveEigen()
    
    model.calcMooringAndOffsets()    # calculate the offsets for the given loading

    model.solveDynamics()            # put everything together and iteratively solve the dynamic response

    model.plot()
    
    plt.show()
    
    return model
    

    
    
def runRAFTfromWEIS():    
    ''' this is the more realistic case where we have to process wt_opt to produce memberStrings and MooringSystem <<<<<<<'''
        
    # Members
    floating_init_options = modeling_options['floating']  # I need to include these because this is where we get name_member
    n_members = floating_init_options['members']['n_members'] 
    
    n_joints = len(wt_opt['floating.floating_joints.location'])
    rA = np.zeros([n_joints, 2])
    rB = np.zeros([n_joints, 2])
    for i in range(n_joints):
        joint_locs[i,:] = wt_opt['floating.floating_joints.location'][i,:]
    
    for i in range(n_members):
        name_member = floating_init_options['members']['name'][i]
        type = 2 # arbitrary value to designate that the member is part of the floating substructure
        
        dA = wt_opt['floating.floating_member_' + name_member + '.outer_diameter'][0]
        dB = wt_opt['floating.floating_member_' + name_member + '.outer_diameter'][1]
        # <<<<<<<< the IEA ontology paper says that the outer_diameter parameter describes two diameters at joints 1 and 2
        
        t = sum(wt_opt['floating.floating_member_' + name_member + '.layer_thickness'])
        # took the sum of this because we just want to know the total thickness to get to dB
        # <<<<<<<<< not sure if I summed it right because the thickness of each layer is [j,:] in gc_WT_InitModel
        
        if n_joints != n_members + 1:
            raise ValueError('There should be n_members+1 number of joints to use the right rA and rB values')
        rA = joint_locs[i,:]
        rB = joint_locs[i+1,:]
        
        # <<<<<<<<<<< Ballast section: PROBABLY WON'T WORK. JUST USING WHAT I WAS GIVEN
        v_fill = wt_opt['floating.floating_member_' + name_member + '.ballast_volume'] 
        rho_fill = wt_opt['floating.floating_member_' + name_member + '.ballast_material.rho']

        #dB_fill = (dBi-dAi)*(self.l_fill/self.l) + dAi       # interpolated diameter of member where the ballast is filled to
        #v_fill = (np.pi/4)*(1/3)*(dAi**2+dB_fill**2+dAi*dB_fill)*self.l_fill    #[m^3]
        # There's a way to solve for l_fill using the above equations given v_fill
        
        # Going to simplify and just take it as the proportion of length to volume
        dAi = dA - 2*t # assming the thickness is constant along the member with respect to the length
        dBi = dB - 2*t
        l = np.linalg.norm(rB-rA)
        v_mem = (np.pi/4)*(1/3)*(dAi**2+dBi**2+dAi*dBi)*l
        
        l_fill = l * v_fill/v_mem
        
        # plug variables into a Member in FrequencyDomain and append to the memberString list
                    # change to string in FD v
        memberStrings.append(raft.Member( str(name_member)+" "+str(type)+" "+str(dA)+" "+str(dB)+" "+str(rA[0])+" "+str(rA[1])+" "+str(rA[2])+\
                                 " "+str(rB[0])+" "+str(rB[1])+" "+str(rB[2])+" "+str(t)+" "+str(l_fill)+" "+str(rho_fill), nw))
  
  
    
    # Create a MoorPy system
    ms = mp.System()
    ms.depth = wt_opt['env.water_depth']
    
    # Add the line types that are provided in the wt_opt OpenMDAO object
    n_line_types = len(wt_opt['mooring.line_diameter'])
    for i in range(n_line_types):
        name = wt_opt['mooring.line_names'][i]
        d = wt_opt['mooring.line_diameter'][i]
        massden = wt_opt['mooring.line_mass_density'][i]
        EA = wt_opt['mooring.line_stiffness'][i]
        MBL = wt_opt['mooring.line_breaking_load'][i]
        cost = wt_opt['mooring.line_cost'][i]
        
        ms.LineTypes[name] = mp.LineType( name, d, massden, EA, MBL=MBL, cost=cost, notes="made in FrequencyDomain.py" )
        
    # Add the wind turbine platform reference point   <<<<<<<<<<<<<< Get values
    ms.addBody(0, PRP, m=mTOT, v=VTOT, rCG=rCG_TOT, AWP=AWP_TOT, rM=np.array([0,0,zMeta]), f6Ext=np.array([Fthrust,0,0, 0,Mthrust,0]))
    
    # Add points to the sytem
    for i in range(n_nodes):
        ID = wt_opt['mooring.node_id'][i]            # <<<<<<<<< not 100% on the syntax of these calls
        
        if wt_opt['mooring.node_type'][i] == 'fixed':
            type = 1
        elif wt_opt['mooring.node_type'][i] == 'vessel':
            type = -1
        elif wt_opt['mooring.node_type'][i] == 'connection':
            type = 0
        
        r = np.array( wt_opt['mooring.nodes_location'][i,:], dtype=float)
        # TODO - can add in other variables for the point like anchor ID, fairlead_type, node_mass, node_volume, drag area, added mass
        ms.PointList.append( mp.Point( ID, type, r ) )

        # attach body points to the body
        # the nodes_location array is relative to inertial frame if Fixed or Connect, but relative to platform frame if Vessel
        if type==-1:
            ms.BodyList[0].addPoint(ID, r)
        
    
    # Add and attach lines to the nodes of the system
    n_lines = len(wt_opt['mooring.unstretched_length'])
    for i in range(n_lines):
        ID = wt_opt['mooring.line_id'][i]
        LineLength = wt_opt['mooring.unstretched_length'][i]
        linetype = wt_opt['mooring.line_type'][i]
        
        ms.LineList.append( mp.Line( ID, LineLength, LineTypes[linetype] ) )
        
        node1 = wt_opt['mooring.node1_id']
        node2 = wt_opt['mooring.node2_id']
        # Run an if statement to make sure that node1 is the deeper point
        if ms.PointList[node1].r[2] < ms.PointList[node2].r[2]:
            pass
        elif ms.PointList[node1].r[2] > ms.PointList[node2].r[2]:
            node1 = node2
            node2 = node1
        else:
            pass # if the z value of both points is the same, then it doesn't matter
        
        ms.PointList[node1].addLine(ID, 0)
        ms.PointList[node2].addLine(ID, 1)
    
        # TODO - anchor types
        
        # Turn on the system
        ms.initialize()
        MooringSystem = ms

    # NEED TO ADD THE FINAL MODEL RUN STEPS HERE ONCE THE ABOVE WORKS

    

if __name__ == "__main__":
    
    
    #model = runRAFT('../designs/OC3spar.yaml', 'env.yaml')
    #model = runRAFT('../designs/OC4semi.yaml', 'env.yaml')
    #model = runRAFT('../designs/VolturnUS-S.yaml', 'env.yaml')
    model = runRAFT('../designs/DTU10MW.yaml', 'env.yaml')
    fowt = model.fowtList[0]
    
    
    
    
    """
    # ----- temporary script for comparing hydro coefficient curves -----

    # load the design
    with open('OC3spar.yaml') as file:
        design = yaml.load(file, Loader=yaml.FullLoader)
        
    depth = float(design['mooring']['water_depth'])
    w = np.arange(0.1, 5, 0.1)  # frequency range (to be set by modeling options yaml)
    
    # Create the model and compute hydrodynamic constants (with BEM)
    model1 = raft.Model(design, w=w, depth=depth)  # set up model
    model1.setEnv(spectrum="unit")  # set basic wave and wind info
    model1.calcSystemProps()          # get all the setup calculations done within the model
    
    # now turn off PotMod in the design dictionary
    for mi in design['platform']['members']:    mi['potMod'] = False
        
    # Create another model and compute hydrodynamic constants (with strip theory only)
    model2 = raft.Model(design, w=w, depth=depth)  # set up model
    model2.setEnv(spectrum='unit')
    model2.calcSystemProps()          # get all the setup calculations done within the model
    
    
    fix, ax = plt.subplots(3,1, sharex=True)
    for i, j in enumerate([0,2,4]):       # go through surge, heave, and pitch
        ax[i].plot(model1.w, model1.fowtList[0].F_BEM       [j].real, 'b'  , label="F BEM real")
        ax[i].plot(model1.w, model1.fowtList[0].F_BEM       [j].imag, 'b--', label="F BEM imag")
        ax[i].plot(model2.w, model2.fowtList[0].F_hydro_iner[j].real, 'g'  , label="F Froude-Kry real")
        ax[i].plot(model2.w, model2.fowtList[0].F_hydro_iner[j].imag, 'g--', label="F Froude-Kry imag")
    ax[-1].legend()
    
    ax[0].set_ylabel('surge')
    ax[1].set_ylabel('heave')
    ax[2].set_ylabel('pitch')
    
    
    # plot member distributed stuff now
    
    f = model2.fowtList[0]
    
    n = f.memberList[0].F_exc_iner.shape[0]
    n3 = int(np.ceil(n/3))
    
    fig, ax = plt.subplots(n3,3, sharex=True)
    for i in range(3):       # go through surge, heave, and pitch
        for j in range(n3):
        
            k = i*n3 + j
            
            if k < n:
                    
                ax[j,i].axhline(0.0, color='k', lw=0.4)
                ax[j,i].plot(model2.w, model2.fowtList[0].memberList[0].F_exc_iner[k,0,:].real, 'g'  , label="Fx real")
                ax[j,i].plot(model2.w, model2.fowtList[0].memberList[0].F_exc_iner[k,0,:].imag, 'g--', label="Fx imag")
                ax[j,i].plot(model2.w, model2.fowtList[0].memberList[0].F_exc_iner[k,2,:].real, 'r'  , label="Fz real")
                ax[j,i].plot(model2.w, model2.fowtList[0].memberList[0].F_exc_iner[k,2,:].imag, 'r--', label="Fz imag")
                ax[j,i].set_ylabel(f"strip {k}")
        
    ax[-1,-1].legend()
    
    
    plt.show()
    """
    
