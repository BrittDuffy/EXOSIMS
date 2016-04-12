# -*- coding: utf-8 -*-
import numpy as np
import sys
import astropy.units as u
import astropy.constants as const
import copy
import logging
from EXOSIMS.util.get_module import get_module
from EXOSIMS.util.deltaMag import deltaMag

# the EXOSIMS logger
Logger = logging.getLogger(__name__)

class SurveySimulation(object):
    """Survey Simulation class template
    
    This class contains all variables and methods necessary to perform
    Survey Simulation Module calculations in exoplanet mission simulation.
    
    It inherits the following class objects which are defined in __init__:
    Simulated Universe, Observatory, TimeKeeping, PostProcessing
    
    Args:
        \*\*specs:
            user specified values
            
    Attributes:
        SimulatedUniverse (SimulatedUniverse):
            SimulatedUniverse class object
        Observatory (Observatory):
            Observatory class object
        TimeKeeping (TimeKeeping):
            TimeKeeping class object
        PostProcessing (PostProcessing):
            PostProcessing class object
        TargetList (TargetList):
            TargetList class object
        PlanetPhysicalModel (PlanetPhysicalModel):
            PlanetPhysicalModel class object
        OpticalSystem (OpticalSystem):
            OpticalSystem class object
        PlanetPopulation (PlanetPopulation):
            PlanetPopulation class object
        ZodiacalLight (ZodiacalLight):
            ZodiacalLight class object
        Completeness (Completeness):
            Completeness class object
        DRM (list):
            list containing results of survey simulation
        
    """

    _modtype = 'SurveySimulation'
    _outspec = {}
    
    def __init__(self,scriptfile=None,**specs):
        """Initializes Survey Simulation with default values
        
        Input: 
            scriptfile:
                JSON script file.  If not set, assumes that 
                dictionary has been passed through specs 
            specs: 
                Dictionary containing user specification values and 
                a dictionary of modules.  The module dictionary can contain
                string values, in which case the objects will be instantiated,
                or object references.
        """

        # if a script file is provided read it in
        if scriptfile is not None:
            import json
            import os.path
        
            assert os.path.isfile(scriptfile), "%s is not a file."%scriptfile

            try:
                script = open(scriptfile).read()
                specs = json.loads(script)
            except ValueError:
                print "%s improperly formatted."%scriptfile
            except:
                print "Unexpected error:", sys.exc_info()[0]
                raise

            # modules array must be present
            if 'modules' not in specs.keys():
                raise ValueError("No modules field found in script.")

        #if any of the modules is a string, assume that they are all strings and we need to initalize
        if isinstance(specs['modules'].itervalues().next(),basestring):

            # import desired module names (prototype or specific)
            self.SimulatedUniverse = get_module(specs['modules'] \
                    ['SimulatedUniverse'],'SimulatedUniverse')(**specs)
            self.Observatory = get_module(specs['modules'] \
                    ['Observatory'],'Observatory')(**specs)
            self.TimeKeeping = get_module(specs['modules'] \
                    ['TimeKeeping'],'TimeKeeping')(**specs)

            # bring inherited class objects to top level of Survey Simulation
            SU = self.SimulatedUniverse
            self.OpticalSystem = SU.OpticalSystem
            self.PlanetPopulation = SU.PlanetPopulation
            self.ZodiacalLight = SU.ZodiacalLight
            self.BackgroundSources = SU.BackgroundSources
            self.Completeness = SU.Completeness
            self.PlanetPhysicalModel = SU.PlanetPhysicalModel
            self.PostProcessing = SU.PostProcessing
            self.TargetList = SU.TargetList
        else:
            #these are the modules that must be present if passing instantiated objects
            neededObjMods = ['SimulatedUniverse',
                          'Observatory',
                          'TimeKeeping',
                          'PostProcessing',
                          'OpticalSystem',
                          'PlanetPopulation',
                          'ZodiacalLight',
                          'Completeness',
                          'PlanetPhysicalModel',
                          'TargetList']

            #ensure that you have the minimal set
            for modName in neededObjMods:
                if modName not in specs['modules'].keys():
                    raise ValueError("%s module not provided."%modName)

            for modName in specs['modules'].keys():
                assert (specs['modules'][modName]._modtype == modName), \
                "Provided instance of %s has incorrect modtype."%modName

                setattr(self, modName, specs['modules'][modName])

        # list of simulation results, each item is a dictionary
        self.DRM = []
    
    def __str__(self):
        """String representation of the Survey Simulation object
        
        When the command 'print' is used on the Survey Simulation object, this 
        method will return the values contained in the object"""

        atts = self.__dict__.keys()
        
        for att in atts:
            print '%s: %r' % (att, getattr(self, att))
        
        return 'Survey Simulation class object attributes'
        
    def run_sim(self):
        """Performs the survey simulation 
        
        This method has access to the following:
            self.SimulatedUniverse:
                SimulatedUniverse class object
            self.Observatory:
                Observatory class object
            self.TimeKeeping:
                TimeKeeping class object
            self.PostProcessing:
                PostProcessing class object
            self.OpticalSystem:
                OpticalSystem class object
            self.PlanetPopulation:
                PlanetPopulation class object
            self.ZodiacalLight:
                ZodiacalLight class object
            self.Completeness:
                Completeness class object
            self.PlanetPhysicalModel:
                PlanetPhysicalModel class object
            self.TargetList:
                TargetList class object
        
        Returns:
            string (str):
                String 'Simulation results in .DRM'
        
        """
        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem
        PPop = self.PlanetPopulation
        
        Logger.info('run_sim beginning')
        # initialize values updated later
        # number of visits to target star
        visited = np.zeros(TL.nStars,dtype=int)
        # target revisit list
        revisit_list = np.array([])
        extended_list = np.array([])
        # current time (normalized to zero at mission start) of planet positions
        planPosTime = np.array([TK.currenttimeNorm.to('day').value]*SU.nPlans)*u.day
        # number of planet observations
        observed = np.zeros((SU.nPlans,), dtype=int)
        # set occulter separation if haveOcculter
        if OS.haveOcculter:
            Obs.currentSep = Obs.occulterSep
        
        # initialize run options
        # perform characterization if doChar = True
        doChar = self.PostProcessing.SNchar > 0
        # keep track of spectral characterizations, 0 is no characterization
        spectra = np.zeros((SU.nPlans,1), dtype=int)
        # get index of first target star
        sInd = self.initial_target()
        
        # loop until mission is finished
        while not TK.mission_is_over():
            Logger.info('current time is %r' % TK.currenttimeNorm)
            print 'Current mission time: ', TK.currenttimeNorm
            obsbegin = copy.copy(TK.currenttimeNorm)

            # dictionary containing results
            DRM = {}
            DRM['target_ind'] = sInd                                 # target star index
            DRM['arrival_time'] = TK.currenttimeNorm.to('day').value # arrival time
            if OS.haveOcculter:
                DRM['scMass'] = Obs.scMass.to('kg').value            # spacecraft mass

            # get target list star index of detections for extended_list 
            if TK.currenttimeNorm > TK.missionLife and extended_list.shape[0] == 0:
                for i in xrange(len(self.DRM)):
                    if self.DRM[i]['det'] == 1:
                        extended_list = np.hstack((extended_list, self.DRM[i]['target_ind']))
                        extended_list = np.unique(extended_list)
            
            # filter planet indices
            pInds = np.where(SU.plan2star == sInd[0])[0]        # belonging to target star
            WA = SU.get_current_WA(pInds)
            pInds = pInds[np.logical_and(WA>OS.IWA,WA<OS.OWA)]  # inside [IWA-OWA]
            dMag = deltaMag(SU.p[pInds],SU.Rp[pInds],SU.d[pInds],PPop.calc_Phi(SU.r[pInds]))
            pInds = pInds[dMag < OS.dMagLim]                    # bright enough

            # update visited list for current star
            visited[sInd] += 1
            # find out if observations are possible and get relevant data
            observationPossible, t_int, DRM = self.observation_detection(pInds, sInd, DRM, planPosTime)
            t_int += Obs.settlingTime
            # store detection integration time
            DRM['det_int_time'] = t_int.to('day').value

            # patch negative t_int
            if (t_int<0).any():
                Logger.warning('correcting negative t_int to arbitrary value')
                t_int = (1.0+np.random.rand())*u.day
            
            if not TK.allocate_time(t_int):
                # time too large: skip it
                observationPossible = False
                TK.allocate_time(1.0*u.day)

            # determine detection, missed detection, false alarm booleans
            FA, DET, MD, NULL = self.PostProcessing.det_occur(observationPossible)

            # apparent separation placeholders
            if pInds.size == 0:
                s = np.array([1.])*u.AU
            else:
                s = SU.s[pInds]
            # encode detection status
            s, DRM, observed = self.det_data(s, DRM, FA, DET, MD, sInd, pInds, \
                    observationPossible, observed)
            
            if doChar:
                DRM, FA, spectra = self.observation_characterization(observationPossible, \
                pInds, sInd, spectra, DRM, FA, t_int)
             
            # schedule a revisit
            if pInds.shape[0] and (DET or FA):
                # if there are planets, revisit based on planet with minimum separation
                sp = np.min(s)
                Mp = SU.Mp[pInds[np.argmin(s)]]
                mu = const.G*(Mp + TL.MsTrue[sInd]*const.M_sun)
                T = 2.*np.pi*np.sqrt(sp**3/mu)
                t_rev = TK.currenttimeNorm + T/2.
            else:
                # revisit based on average of population semi-major axis and mass
                sp = SU.s.mean()
                Mp = SU.Mp.mean()
                mu = const.G*(Mp + TL.MsTrue[sInd]*const.M_sun)
                T = 2.*np.pi*np.sqrt(sp**3/mu)
                t_rev = TK.currenttimeNorm + 0.75*T

###fix this!
            # populate revisit list (sInd is converted to float)
            if revisit_list.size == 0:
                revisit_list = np.hstack((revisit_list, np.array([sInd[0], t_rev.to('day').value])))
            else:
                revisit_list = np.vstack((revisit_list, np.array([sInd[0], t_rev.to('day').value])))
           

            ### more methods inside timekeeping
            obsend = copy.copy(TK.currenttimeNorm)
            # find next available time for planet-finding
            nexttime = TK.currenttimeNorm
            
            # update completeness values
            TL.comp0 = self.Completeness.completeness_update(sInd, TL, obsbegin, obsend, nexttime)
            
            # acquire a new target star index
            sInd, DRM = self.next_target(sInd, DRM)
            
            # append result values to self.DRM
            self.DRM.append(DRM)
            
            # with occulter if spacecraft fuel is depleted, exit loop
            if OS.haveOcculter:
                if Obs.scMass < Obs.dryMass:
                    print 'Total fuel mass exceeded at %r' % TK.currenttimeNorm
                    break

#            if visited[sInd] == 3:
#                TK.currenttimeNorm = 100*u.year
#            if TK.currenttimeNorm > 100*u.day:
#                TK.currenttimeNorm = 100*u.year
        
        Logger.info('run_sim finishing OK')
        print 'Survey simulation: finishing OK'
        return 'Simulation results in .DRM'



###fold into next target determination
    def initial_target(self):
        """Returns index of initial target star
        
        This method has access to the following:
            self.SimulatedUniverse:
                SimulatedUniverse class object
            self.Observatory:
                Observatoryervatory class object
            self.TimeKeeping:
                TimeKeeping class object
            self.PostProcessing:
                PostProcessing class object
            self.OpticalSystem:
                OpticalSystem class object
            self.PlanetPopulation:
                PlanetPopulation class object
            self.ZodiacalLight:
                ZodiacalLight class object
            self.Completeness:
                Completenessleteness class object
            self.PlanetPhysicalModel:
                PlanetPhysicalModel class object
            self.TargetList:
                TargetList class object
        
        Returns:
            sInd (integer ndarray):
                index of initial target star, or None
        """
        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem

        while not TK.mission_is_over():
            a = Obs.keepout(TK.currenttimeAbs, TL, OS.telescopeKeepout)
            # find observable targets at current mission time            
            sInds = np.where(Obs.kogood)[0]
            # if no observable targets, advance mission time by a nominal dt, try again
            if sInds.size == 0:
                TK.allocate_time(1.0*u.day)
            else:
                break # found target(s)
        
        if TK.mission_is_over() or sInds.size == 0:
            Logger.info('No more targets available')
            return None

        # pick one
        s0 = TL.comp0[sInds].argmax()
        sInd = np.array([sInds[s0]])
        
        return sInd
       

####cleanup all offloaded to opticalsystem
    def observation_detection(self, pInds, sInd, DRM, planPosTime):
        """Finds if planet observations are possible and relevant information
        
        This method makes use of the following inherited class objects:
        
        Args:
            pInds (ndarray):
                1D numpy ndarray of planet indices
            sInd (int):
                target star index
            DRM (dict):
                dictionary containing simulation results
            planPosTime (Quantity):
                1D numpy ndarray containing times of planet positions (units of
                time)
        
        Returns:
            observationPossible, t_int, DRM (ndarray, Quantity, dict, Quantity, ndarray, Quantity):
                1D numpy ndarray of booleans indicating if an observation of 
                each planet is possible, integration time (units of time), 
                dictionary containing survey simulation results, apparent 
                separation (units of distance), 1D numpy ndarray of delta 
                magnitude, difference in magnitude between planet and star,
                irradiance (units of :math:`1/(m^2*nm*s)`)
        
        """
        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem
        PPop = self.PlanetPopulation

        # determine if there are any planets at the target star and
        # propagate the system if necessary
        if pInds.shape[0] != 0:
            # there are planets so observation is possible
            observationPossible = np.ones((len(pInds),), dtype=bool)
            # if planet position times do not match up with current time
            # propagate the positions to the current time
            if planPosTime[pInds][0] != TK.currenttimeNorm:
                # propagate planet positions and velocities
                try:
                    SU.r[pInds], SU.v[pInds],SU.s[pInds],SU.d[pInds] = \
                            SU.prop_system(SU.r[pInds],SU.v[pInds],SU.Mp[pInds],\
                            TL.MsTrue[SU.plan2star[pInds]],TK.currenttimeNorm \
                            - planPosTime[pInds][0])
                    # update planet position times
                    planPosTime[pInds] = TK.currenttimeNorm
                except ValueError:
                    observationPossible = False
        else:
            observationPossible = False

        # set integration time to max integration time as a default
        t_int = OS.calc_maxintTime(TL)
            
        # determine integration time and update observationPossible
        if np.any(observationPossible):
            # find true integration time
            t_trueint = OS.calc_intTime(TL,sInd,SU.I[pInds],deltaMag(SU.p[pInds],SU.Rp[pInds],\
                    SU.d[pInds],PPop.calc_Phi(SU.r[pInds])),SU.get_current_WA(pInds))
            # update observationPossible
            observationPossible = np.logical_and(observationPossible,\
                    t_trueint <= OS.intCutoff)

        # determine if planets are observable at the end of observation
        # and update integration time
        if np.any(observationPossible):
            try:
                t_int, observationPossible = self.check_visible_end(observationPossible, t_int, t_trueint, sInd, pInds, False)
            except ValueError:
                observationPossible = False
                
        if OS.haveOcculter:
            # find disturbance forces on occulter
            dF_lateral, dF_axial = Obs.distForces(TK, TL, sInd)
            # store these values
            DRM['dF_lateral'] = dF_lateral.to('N').value
            DRM['dF_axial'] = dF_axial.to('N').value
            # decrement mass for station-keeping
            intMdot, mass_used, deltaV = Obs.mass_dec(dF_lateral, t_int)
            # store these values
            DRM['det_dV'] = deltaV.to('m/s').value
            DRM['det_mass_used'] = mass_used.to('kg').value
            Obs.scMass -= mass_used
            
        return observationPossible, t_int, DRM
        
    def observation_characterization(self, observationPossible, pInds, sInd, spectra, DRM, FA, t_int):
        """Finds if characterizations are possible and relevant information
        
        Args:
            observationPossible (ndarray):
                1D numpy ndarray of booleans indicating if an observation of 
                each planet is possible
            pInds (ndarray):
                1D numpy ndarray of planet indices
            sInd (int):
                target star index
            spectra (ndarray):
                numpy ndarray of values indicating if planet spectra has been
                captured
            DRM (dict):
                dictionary containing survey simulation results
            FA (bool):
                False Alarm boolean
            t_int (Quantity):
                integration time (units of time)
        
        Returns:
            DRM, FA, spectra (dict, bool, ndarray):
                dictionary containing survey simulation results, False Alarm 
                boolean, numpy ndarray of values indicating if planet spectra 
                has been captured                
                
        """
        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem
        PPop = self.PlanetPopulation

        # check if characterization has been done
        if pInds.shape[0] != 0:
            if np.any(spectra[pInds[observationPossible],0] == 0):
                # perform first characterization
                # find characterization time
                t_char = OS.calc_charTime(TL,sInd,SU.I[pInds],deltaMag(SU.p[pInds],SU.Rp[pInds],\
                        SU.d[pInds],PPop.calc_Phi(SU.r[pInds])),SU.get_current_WA(pInds))
                # patch negative t_char
                if np.any(t_char < 0):
                    Logger.warning('correcting negative t_char to arb. value')
                    t_char_value = (4+2*np.random.rand())*u.day
                    t_char[t_char < 0] = t_char_value

                # account for 5 bands and one coronagraph
                t_char = t_char*4
                # determine which planets will be observable at the end
                # of observation
                charPossible = observationPossible
                charPossible = np.logical_and(charPossible, t_char <= OS.intCutoff)
                chargo = False

                try:
                    t_char, charPossible, chargo = self.check_visible_end(charPossible, \
                            t_char, t_char, sInd, pInds, True)
                except ValueError:
                    chargo = False

                if chargo:
                    # encode relevant first characterization data
                    if OS.haveOcculter:
                        # decrement sc mass
                        # find disturbance forces on occulter
                        dF_lateral, dF_axial = Obs.distForces(TK, TL, sInd)
                        # decrement mass for station-keeping
                        intMdot, mass_used, deltaV = Obs.mass_dec(dF_lateral, t_int)
                        mass_used_char = t_char*intMdot
                        deltaV_char = dF_lateral/Obs.scMass*t_char
                        Obs.scMass -= mass_used_char
                        # encode information in DRM
                        DRM['char_1_time'] = t_char.to('day').value
                        DRM['char_1_dV'] = deltaV_char.to('m/s').value
                        DRM['char_1_mass_used'] = mass_used_char.to('kg').value
                    else:
                        DRM['char_1_time'] = t_char.to('day').value
                
                    # if integration time goes beyond observation duration, set quantities
                    # Before, for some reason, an extra 1.0d was added to time if characterization failed. Removed.
                    if not TK.allocate_time(t_char.max()):
                        charPossible = False
                            
                    # if this was a false alarm, it has been noted, update FA
                    if FA:
                        FA = False
                        
                    # if planet is visible at end of characterization,
                    # spectrum is captured
                    if np.any(charPossible):
                        if OS.haveOcculter:
                            spectra[pInds[charPossible],0] = 1
                            # encode success
                            DRM['char_1_success'] = 1
                        else:
                            nld = OS.IWA.to('rad').value / (OS.Spectro['lam']/OS.pupilDiam)
                            lambdaeff = np.arctan(SU.s[pInds]/(TL.dist[sInd])).value
                            lambdaeff *= np.sqrt(OS.pupilArea/OS.shapeFac)
                            lambdaeff /= nld
                            charPossible = np.logical_and(charPossible, lambdaeff >= 800.*u.nm)
                            # encode results
                            if np.any(charPossible):
                                spectra[pInds[charPossible],0] = 1
                                DRM['char_1_success'] = 1
                            else:
                                DRM['char_1_success'] = lambdaeff.max().to('nm').value
                       
        return DRM, FA, spectra


    def check_visible_end(self, observationPossible, t_int, t_trueint, sInd, pInds, t_char_calc):
        """Determines if planets are visible at the end of the observation time
        
        This method makes use of the following inherited objects:
            TL:
                TargetList class object
            Obs:
                Observatory class object
            TK:
                TimeKeeping class object
            SU:
                SimulatedUniverse class object
            OS:
                OpticalSystem class object
                
        Args:
            observationPossible (ndarray):
                1D numpy ndarray of booleans indicating if an observation of 
                each planet is possible
            t_int (Quantity):
                integration time (units of time)
            t_trueint (Quantity):
                1D numpy ndarray of calculated integration times for planets
                (units of time)
            sInd (int):
                target star index
            pInds (ndarray):
                1D numpy ndarray of planet indices
            t_char_calc (bool):
                boolean where True is for characterization calculations
                
        Returns:
            t_int, observationPossible, chargo (Quantity, ndarray, bool):
                true integration time for planetary system (units of day) 
                (t_char_calc = False) or maximum characterization time for 
                planetary system (t_char_calc = True), updated 1D numpy ndarray 
                of booleans indicating if an observation or characterization of 
                each planet is possible, boolean where True is to encode 
                characterization data (t_char_calc = True only)
        
        """

        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem
        
        # set chargo to False initially
        chargo = False
        
        for i in xrange(len(observationPossible)):
            if observationPossible[i]:
                r = SU.r[pInds[i]]
                v = SU.v[pInds[i]]
                Mp = SU.Mp[pInds[i]]
                MsTrue = TL.MsTrue[sInd]
                Rp = SU.Rp[pInds[i]]
                p = SU.p[pInds[i]]
                if t_char_calc:
                    dt = t_int[i]
                else:
                    dt = t_trueint[i] + Obs.settlingTime

                obsRes = self.sys_end_res(dt, sInd, r, v, Mp, MsTrue, Rp, p)

                if obsRes == 1:
                    # planet visible at the end of observation
                    observationPossible[i] = True
                    if not t_char_calc:
                        # update integration time
                        if t_int == TL.maxintTime[sInd]:
                            t_int = t_trueint[i]
                        else:
                            if t_trueint[i] > t_int:
                                t_int = t_trueint[i]
                
                if obsRes != -1:
                    if t_char_calc:
                        chargo = True
                        
        if t_char_calc:
            if np.any(observationPossible):
                t_int = np.max(t_int[observationPossible])
            
            return t_int, observationPossible, chargo
        else:
            return t_int, observationPossible


    def sys_end_res(self, dt, sInd, r, v, Mp, MsTrue, Rp, p):
        """Determines if a planet is visible at the end of the observation time
        
        This method makes use of the following inherited objects:
            Obs:
                Observatory class object
            TK:
                TimeKeeping class object
            TL:
                TargetList class object
            OS:
                OpticalSystem class object
                
        Args:
            dt (Quantity):
                propagation time (units of time)
            sInd (int):
                target star index
            r (Quantity):
                planet position vector as 1D numpy ndarray (units of distance)
            v (Quantity):
                planet velocity vector as 1D numpy ndarray (units of velocity)
            Mp (Quantity):
                planetary mass (units of mass)
            MsTrue (float):
                stellar mass (in M_sun)
            Rp (Quantity):
                planet radius (units of distance)
            p (ndarray):
                planet albedo
                
        Returns:
            obsRes (int):
                -1 if star is inside the keepout zone, 0 if planet is not 
                visible, or 1 if planet is visible
        
        """
        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem

        # update keepout to end of observation time
        a = Obs.keepout(TK.currenttimeAbs+dt, TL, OS.telescopeKeepout)
        # if star is not inside keepout zone at end of observation, see if 
        # planet is still observable
        if Obs.kogood[sInd]:
            # propagate planet to observational period end and find dMagend
            rend, vend, send, dend = SU.prop_system(r, v, Mp, MsTrue, dt)
            beta = np.arccos(rend[2]/dend).value
            Phi = (np.sin(beta) + (np.pi - beta)*np.cos(beta))/np.pi
            dMagend = -2.5*np.log10((p*(Rp/dend)**2*Phi).decompose().value)

            if np.logical_and(dMagend <= OS.dMagLim, send >= TL.dist[sInd].to('km')*np.tan(OS.IWA)):
                obsRes = 1
            else:
                obsRes = 0
        else:
            obsRes = -1
            
        return obsRes

    def det_data(self, s, DRM, FA, DET, MD, sInd, pInds, observationPossible, observed):
        """Determines detection status
        
        This method encodes detection status (FA, DET, MD) values in the DRM 
        dictionary.

        This method accesses the following inherited class objects:
            OS:
                OpticalSystem class object
            TL:
                TargetList class object
            self.PlanetPopulation:
                PlanetPopulation class object
        
        Args:
            s (Quantity):
                apparent separation (units of distance)
            DRM (dict):
                dictionary containing simulation results
            FA (bool):
                Boolean signifying False Alarm
            DET (bool):
                Boolean signifying DETection
            MD (bool):
                Boolean signifying Missed Detection
            sInd (int):
                index of star in target list
            pInds (ndarray):
                idices of planets belonging to target star
            observationPossible (ndarray):
                1D numpy ndarray of booleans indicating if an observation of 
                each planet is possible
            observed (ndarray):
                1D numpy ndarray indicating number of observations for each
                planet
        
        Returns:
            s, DRM, observed (Quantity, dict, ndarray):
                apparent separation (units of distance), delta magnitude, 
                irradiance (units of flux per time), dictionary containing 
                simulation results, 1D numpy ndarray indicating number of 
                observations for each planet                
        
        """
        
        Obs = self.Observatory
        SU = self.SimulatedUniverse
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem

        # default DRM detection status to null detection
        DRM['det_status'] = 0
        
        if FA:
            # false alarm
            DRM['det_status'] = -2
            if self.PlanetPopulation.scaleOrbits:
                s += np.random.rand()*(self.PlanetPopulation.arange.max() - \
                        self.PlanetPopulation.arange.min())*np.sqrt(TL.L[sInd])
            else:
                s += np.random.rand()*(self.PlanetPopulation.arange.max() - \
                        self.PlanetPopulation.arange.min())
        elif MD:
            # missed detection, set status in DRM
            DRM['det_status'] = -1
        elif DET:
            # encode detection
            observed[pInds[observationPossible]] += 1
            if pInds.shape[0] == 1:
                # set status in DRM
                DRM['det_status'] = 1
                # set WA and Delta Mag of detection in DRM
                DRM['det_WA'] = np.arctan(s/(TL.dist[sInd])).to('mas')[0].value
                DRM['det_dMag'] = deltaMag(SU.p[pInds],SU.Rp[pInds],SU.r[pInds])[0]
            else:
                DRM['det_status'] = observationPossible.astype(int).tolist()
                DRM['det_WA'] = np.arctan(s/(TL.dist[sInd])).to('mas').min().value
                DRM['det_dMag'] = (dMag[observationPossible]).max()
        
        return s, DRM, observed
        
    def next_target(self, sInd, DRM):
        """Finds index of next target star
        
        This method chooses the next target star index at random based on which
        stars are available.
        
        This method makes use of the following class objects inherited by the
        SurveySimulation class object:
            TK:
                TimeKeeping class object
            Obs:
                Observatory class object
        
        Args:
            sInd (int):
                index of current target star
            DRM (dict):
                dictionary of simulation results
                
        Returns:
            new_sInd, DRM (int, dict):
                index of next target star, dictionary of simulation results
                new_sInd is None if no target could be found              
        
        """
        
        Obs = self.Observatory
        TL = self.TargetList
        TK = self.TimeKeeping
        OS = self.OpticalSystem

        while not TK.mission_is_over():
            a = Obs.keepout(TK.currenttimeAbs, TL, OS.telescopeKeepout)
            # find observable targets at current mission time
            sinds = np.where(Obs.kogood)[0]
            # if no observable targets, advance mission time by a nominal dt, try again
            if sinds.size == 0:
                TK.allocate_time(1.0*u.day)
            else:
                break # found target(s)
        
        if TK.mission_is_over() or sinds.size == 0:
            Logger.info('No more targets available')
            return None, DRM

        # pick a random star from the stars not in keepout zones
        s0 = np.random.random_integers(0, high=len(sinds)-1)
        new_sInd = np.array([sinds[s0]])
        
        if OS.haveOcculter:
            # add transit time and reduce starshade mass
            ao = Obs.thrust/Obs.scMass
            targetSep = Obs.occulterSep
            # find position vector of previous target star
            r_old = Obs.starprop(TK.currenttimeAbs, TL, sInd)
            # find position vector of new target star
            r_new = Obs.starprop(TK.currenttimeAbs, TL, new_sInd)
            # find unit vectors
            u_old = r_old/np.sqrt(np.sum(r_old**2))
            u_new = r_new/np.sqrt(np.sum(r_new**2))
            # find angle between old and new stars
            sd = np.arccos(np.dot(u_old, u_new))
            # find slew distance
            slew_dist = 2.*targetSep*np.sin(sd/2.)
            slew_time = np.sqrt(slew_dist/np.abs(ao)/(Obs.defburnPortion/2. - Obs.defburnPortion**2/4.))
            mass_used = slew_time*Obs.defburnPortion*Obs.flowRate

            TK.allocate_time(slew_time)
            
            DRM['slew_time'] = slew_time.to('day').value
            DRM['slew_dV'] = (ao*slew_time*Obs.defburnPortion).to('m/s').value
            DRM['slew_mass_used'] = mass_used.to('kg').value
            DRM['slew_angle'] = sd
        
        return new_sInd, DRM
    
