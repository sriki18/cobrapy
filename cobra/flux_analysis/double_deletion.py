from __future__ import with_statement, print_function
#cobra.flux_analysis.double_deletion.py
#runs flux variablity analysis on a Model object.
from copy import deepcopy
from warnings import warn
from os import name as __name
nan = float('nan')
from sys import modules as __modules

from itertools import chain, product
import numpy

from ..solvers import get_solver_name, solver_dict
from ..external.six import iteritems, string_types
from ..manipulation.delete import find_gene_knockout_reactions
from .deletion_worker import CobraDeletionPool, CobraDeletionMockPool

try:
    from .moma import moma    
except:
    def moma(*args, **kwargs):
        raise Exception("moma dependencies missing")

try:
    from pandas import DataFrame
except:
    DataFrame = None

def double_reaction_deletion_fba(cobra_model, reaction_list1=None,
                                 reaction_list2=None, solver=None,
                                 n_processes=None, return_frame=True):
    """setting n_processes=1 explicitly disables multiprocessing"""
    if reaction_list1 is None:
        reaction_indexes1 = range(len(cobra_model.reactions))
    else:
        reaction_indexes1 = [cobra_model.reactions.index(r) for r in reaction_list1]
    if reaction_list2 is None:
        reaction_indexes2 = reaction_indexes1
    else:
        reaction_indexes2 = [cobra_model.reactions.index(r) for r in reaction_list2]

    reaction_indexes = list(set(chain(reaction_indexes1, reaction_indexes2)))
    reaction_to_result = {reaction_index: result_index
                          for result_index, reaction_index in enumerate(reaction_indexes)}
    row_indexes = [reaction_to_result[i] for i in reaction_indexes1]
    row_index_set = set(row_indexes)
    row_names = [cobra_model.reactions[i].id for i in reaction_indexes1]
    column_indexes = [reaction_to_result[i] for i in reaction_indexes2]
    column_index_set = set(column_indexes)
    column_names = [cobra_model.reactions[i].id for i in reaction_indexes2]

    n_results = len(reaction_to_result)
    results = numpy.empty((n_results, n_results))
    results.fill(numpy.nan)

    if n_processes == 1:  # explicitly disable multiprocessing
        pool = CobraDeletionMockPool(cobra_model, n_processes=n_processes, solver=solver)
    else:
        pool = CobraDeletionPool(cobra_model, n_processes=n_processes, solver=solver)
    # submit jobs
    
    for r1_index, r2_index in product(reaction_indexes1, reaction_indexes2):
        r1_result_index = reaction_to_result[r1_index]
        r2_result_index = reaction_to_result[r2_index]
        if r2_result_index >= r1_result_index:  # upper triangle only
            pool.submit((r1_index, r2_index), label=(r1_result_index, r2_result_index))
        # if it's a point only in the lower triangle, compute it
        # and put it in the upper triangle
        elif r1_result_index not in column_index_set or r2_result_index not in row_index_set:
            pool.submit((r1_index, r2_index), label=(r2_result_index, r1_result_index))

    # get results
    for result in pool.receive_all():
        results[result[0]] = result[1]

    del pool

    # reflect results
    triu1, triu2 = numpy.triu_indices(n_results)
    results[triu2, triu1] = results[triu1, triu2]

    results = results[row_indexes, :][:, column_indexes]

    if return_frame and DataFrame:
        return DataFrame(data=results, index=row_names, columns=column_names)

    elif return_frame and not DataFrame:
        warn("could not import pandas.DataFrame")

    return {"x": [cobra_model.reactions.get_by_id(i) for i in row_names],
             "y": [cobra_model.reactions.get_by_id(i) for i in column_names],
             "data": results}

def double_gene_deletion_fba(cobra_model, gene_list1=None, gene_list2=None,
                             solver=None, n_processes=None, return_frame=True):
    if gene_list1 is None:
        gene_list1 = cobra_model.genes
    else:
        gene_list1 = [cobra_model.genes.get_by_id(i)
                      if isinstance(i, string_types) else i
                      for i in gene_list1]
    if gene_list2 is None:
        gene_list2 = gene_list1
    else:
        gene_list2 = [cobra_model.genes.get_by_id(i)
                      if isinstance(i, string_types) else i
                      for i in gene_list2]
    gene_ids1 = [i.id for i in gene_list1]
    gene_ids2 = [i.id for i in gene_list2]
    gene_id_to_result = {}
    n = 0
    for i in gene_ids1:
        if i not in gene_id_to_result:
            gene_id_to_result[i] = n
            n += 1
    for i in gene_ids2:
        if i not in gene_id_to_result:
            gene_id_to_result[i] = n
            n += 1

    row_indexes = [gene_id_to_result[id] for id in gene_ids1]
    row_index_set = set(row_indexes)
    column_indexes = [gene_id_to_result[id] for id in gene_ids2]
    column_index_set = set(column_indexes)

    n_results = len(gene_id_to_result)
    results = numpy.empty((n_results, n_results))
    results.fill(numpy.nan)

    if n_processes == 1:  # explicitly disable multiprocessing
        pool = CobraDeletionMockPool(cobra_model, n_processes=n_processes, solver=solver)
    else:
        pool = CobraDeletionPool(cobra_model, n_processes=n_processes, solver=solver)

    for gene1, gene2 in product(gene_list1, gene_list2):
        g1_result_index = gene_id_to_result[gene1.id]
        g2_result_index = gene_id_to_result[gene2.id]
        if g2_result_index >= g1_result_index:  # upper triangle only
            ko_reactions = find_gene_knockout_reactions(cobra_model, (gene1, gene2))
            ko_indexes = [cobra_model.reactions.index(i) for i in ko_reactions]
            pool.submit(ko_indexes, label=(g1_result_index, g2_result_index))
        # if it's a point only in the lower triangle, compute it
        # and put it in the upper triangle
        elif g1_result_index not in column_index_set or g2_result_index not in row_index_set:
            ko_reactions = find_gene_knockout_reactions(cobra_model, (gene1, gene2))
            ko_indexes = [cobra_model.reactions.index(i) for i in ko_reactions]
            pool.submit(ko_indexes, label=(g2_result_index, g1_result_index))

    for result in pool.receive_all():
        results[result[0]] = result[1]

    del pool

    # reflect results
    triu1, triu2 = numpy.triu_indices(n_results)
    results[triu2, triu1] = results[triu1, triu2]

    results = results[row_indexes, :][:, column_indexes]

    if return_frame and DataFrame:
        return DataFrame(data=results, index=gene_ids1, columns=gene_ids2)

    elif return_frame and not DataFrame:
        warn("could not import pandas.DataFrame")

    return {"x": [cobra_model.genes.get_by_id(i) for i in gene_ids1],
             "y": [cobra_model.genes.get_by_id(i) for i in gene_ids2],
             "data": results}

def double_deletion(cobra_model, element_list_1=None, element_list_2=None,
                    method='fba', single_deletion_growth_dict=None,
                    element_type='gene', solver=None, error_reporting=None,
                    number_of_processes=1):
    """Wrapper for double_gene_deletion and double_reaction_deletion

    cobra_model: a cobra.Model object

    element_list_1: Is None or a list of elements (genes or reactions)
    
    element_list_2: Is None or a list of elements (genes or reactions)

    method: 'fba' or 'moma' to run flux balance analysis or minimization
    of metabolic adjustments.

    single_deletion_growth_dict: A dictionary that provides the growth
    rate information for single gene knock outs.  This can speed up
    simulations because nonviable single deletion strains imply that all
    double deletion strains will also be nonviable.

    element_type: 'gene' or 'reaction'

    solver: 'glpk', 'gurobi', or 'cplex'.

    error_reporting: None or True

    Returns a dictionary of the elements in the x dimension (x), the y
    dimension (y), and the growth simulation data (data).

    """
    if method == "fba":
        if element_type == "gene":
            return double_gene_deletion_fba(cobra_model,
                gene_list1=element_list_1,
                gene_list2=element_list_2, solver=solver,
                return_frame=False,
                n_processes=number_of_processes)
        elif element_type == "reaction":
            return double_reaction_deletion_fba(cobra_model,
                reaction_list1=element_list_1,
                reaction_list2=element_list_2, solver=solver,
                return_frame=False,
                n_processes=number_of_processes)
        else:
            raise ValueError("element_type %s not gene or reaction" % element_type)

    if method != "moma":
        raise ValueError("method %s is not fba or moma" % method)

    if solver is None:
        solver = get_solver_name()

    if number_of_processes > 1:
        warn("parallel moma double deletion not implemented")

    if element_type == 'gene':
        return double_gene_deletion_moma(cobra_model, gene_list_1=element_list_1,
                                    gene_list_2=element_list_2, method=method,
                                    single_deletion_growth_dict=single_deletion_growth_dict,
                                    solver=solver,
                                    error_reporting=error_reporting)
    else:
        raise Exception("Double reaction deletion with moma not yet implemented")

def double_gene_deletion_moma(cobra_model, gene_list_1=None, gene_list_2=None,
                              method='moma', single_deletion_growth_dict=None,
                              solver='glpk', growth_tolerance=1e-8,
                              error_reporting=None):
    """This will disable reactions for all gene pairs from gene_list_1 and
    gene_list_2 and then run simulations to optimize for the objective
    function.  The contribution of each reaction to the objective function
    is indicated in cobra_model.reactions[:].objective_coefficient vector.

    NOTE:  We've assumed that there is no such thing as a synthetic rescue with
    this modeling framework.

    cobra_model: a cobra.Model object

    gene_list_1: Is None or a list of genes.  If None then both gene_list_1
    and gene_list_2 are assumed to correspond to cobra_model.genes.
    
    gene_list_2: Is None or a list of genes.  If None then gene_list_2 is
    assumed to correspond to gene_list_1.

    method: 'fba' or 'moma' to run flux balance analysis or minimization
    of metabolic adjustments.
    
    single_deletion_growth_dict: A dictionary that provides the growth
    rate information for single gene knock outs.  This can speed up
    simulations because nonviable single deletion strains imply that all
    double deletion strains will also be nonviable.

    solver: 'glpk', 'gurobi', or 'cplex'.

    error_reporting: None or True

    growth_tolerance: float.  The effective lower bound on the growth rate
    for a single deletion that is still considered capable of growth.  

    Returns a dictionary of the gene ids in the x dimension (x) and the y
    dimension (y), and the growth simulation data (data).
    
    """
    #BUG: Since this might be called from ppmap, the modules need to
    #be imported.  Modify ppmap to take depfuncs
    from numpy import zeros
    nan = float('nan')
    from cobra.flux_analysis.single_deletion import single_deletion
    from cobra.manipulation import delete_model_genes, undelete_model_genes
    ##TODO: Use keywords instead
    if isinstance(cobra_model, dict):
        tmp_dict = cobra_model
        cobra_model = tmp_dict['cobra_model']
        if 'gene_list_1' in tmp_dict:
            gene_list_1 = tmp_dict['gene_list_1']
        if 'gene_list_2' in tmp_dict:
            gene_list_2 = tmp_dict['gene_list_2']
        if 'method' in tmp_dict:
            method = tmp_dict['method']
        if 'single_deletion_growth_dict' in tmp_dict:
            single_deletion_growth_dict = tmp_dict['single_deletion_growth_dict']
        if 'solver' in tmp_dict:
            solver = tmp_dict['solver']
        if 'error_reporting' in tmp_dict:
            error_reporting = tmp_dict['error_reporting']
    else:
        cobra_model = cobra_model
    #this is a slow way to revert models.
    wt_model = cobra_model  #NOTE: It may no longer be necessary to use a wt_model
    #due to undelete_model_genes
    if gene_list_1 is None:
        gene_list_1 = cobra_model.genes
    elif not hasattr(gene_list_1[0], 'id'):
        gene_list_1 = map(cobra_model.genes.get_by_id, gene_list_1)
    #Get default values to use if the deletions do not alter any reactions
    cobra_model.optimize(solver=solver)
    basal_f = cobra_model.solution.f
    if method.lower() == 'moma':
        wt_model = cobra_model.copy()
        combined_model = None
    single_gene_set = set(gene_list_1)
    if gene_list_2 is not None:
        if not hasattr(gene_list_2[0], 'id'):
            gene_list_2 = map(cobra_model.genes.get_by_id, gene_list_2)
        single_gene_set.update(gene_list_2)
    #Run the single deletion analysis to account for double deletions that
    #target the same gene and lethal deletions.  We assume that there
    #aren't synthetic rescues.
    single_deletion_growth_dict = single_deletion(cobra_model,
                                                  list(single_gene_set),
                                                  method=method,
                                                  solver=solver)[0]
    if gene_list_2 is None or gene_list_1 == gene_list_2:
        number_of_genes = len(gene_list_1)
        gene_list_2 = gene_list_1
        deletion_array = zeros([number_of_genes, number_of_genes]) 
        ##TODO: Speed up this triangular process
        #For the case where the contents of the lists are the same cut the work in half.
        #There might be a faster way to do this by using a triangular array function
        #in numpy
        #Populate the diagonal from the single deletion lists
        for i, the_gene in enumerate(gene_list_1):
            deletion_array[i, i] = single_deletion_growth_dict[the_gene.id]
        for i, gene_1 in enumerate(gene_list_1[:-1]):
            #TODO: Since there cannot be synthetic rescues we can assume
            #that the whole row for a lethal deletion
            #will be equal to that deletion.
            if single_deletion_growth_dict[gene_1.id] < growth_tolerance:
                tmp_solution = single_deletion_growth_dict[gene_1.id]
                for j in range(i+1, number_of_genes):
                    deletion_array[j, i] = deletion_array[i, j] = tmp_solution
            else:
                for j, gene_2 in enumerate(gene_list_1[i+1:], i+1):
                    if single_deletion_growth_dict[gene_2.id] < growth_tolerance:
                        tmp_solution = single_deletion_growth_dict[gene_2.id]
                    else:
                        delete_model_genes(cobra_model, [gene_1, gene_2])
                        if cobra_model._trimmed:
                            if method.lower() == 'fba':
                                #Assumes that the majority of perturbations don't change
                                #reactions which is probably false
                                cobra_model.optimize(solver=solver, error_reporting=error_reporting)
                                the_status = cobra_model.solution.status
                                tmp_solution = cobra_model.solution.f
                            elif method.lower() == 'moma':
                                try:
                                    moma_solution = moma(wt_model, cobra_model,
                                                         combined_model=combined_model,
                                                         solver=solver)
                                    tmp_solution = float(moma_solution.pop('objective_value'))
                                    the_status = moma_solution.pop('status')
                                    combined_model = moma_solution.pop('combined_model')
                                    del moma_solution
                                except:
                                    tmp_solution = nan
                                    the_status = 'failed'
                            if the_status not in ['opt', 'optimal']  and \
                                   error_reporting:
                                print('%s / %s: %s status: %s'%(gene_1, gene_2, solver,
                                                                the_status))
                            #Reset the model to orginial form.
                            undelete_model_genes(cobra_model)
                        else:
                            tmp_solution = basal_f
                    deletion_array[j, i] = deletion_array[i, j] = tmp_solution

    else:
        deletion_array = zeros([len(gene_list_1), len(gene_list_2)])
        #Now deal with the case where the gene lists are different
        for i, gene_1 in enumerate(gene_list_1):
            if single_deletion_growth_dict[gene_1.id] <= 0:
                for j in range(len(gene_list_2)):
                    deletion_array[i, j] = 0.
            else:
                for j, gene_2 in enumerate(gene_list_2):
                    #Assume no such thing as a synthetic rescue
                    if single_deletion_growth_dict[gene_2.id] <= growth_tolerance:
                        tmp_solution = single_deletion_growth_dict[gene_2.id]
                    else:
                        delete_model_genes(cobra_model, [gene_1, gene_2])
                        if cobra_model._trimmed:
                            if method.lower() == 'fba':
                                cobra_model.optimize(solver=solver)
                                tmp_solution = cobra_model.solution.f
                                the_status = cobra_model.solution.status
                            elif method.lower() == 'moma':
                                try:
                                    moma_solution = moma(wt_model, cobra_model,
                                                         combined_model=combined_model,
                                                         solver=solver)
                                    tmp_solution = float(moma_solution.pop('objective_value'))
                                    the_status = moma_solution.pop('status')
                                    combined_model = moma_solution.pop('combined_model')
                                    del moma_solution
                                except:
                                    tmp_solution = nan
                                    the_status = 'failed'
                            if the_status not in ['opt', 'optimal']  and \
                                   error_reporting:
                                print('%s / %s: %s status: %s'%(repr(gene_1), repr(gene_2), solver,
                                                            cobra_model.solution.status))
                            #Reset the model to wt form
                            undelete_model_genes(cobra_model)
                        else:
                            tmp_solution = basal_f
                    deletion_array[i, j] = tmp_solution
    if hasattr(gene_list_1, 'id'):
        gene_list_1 = [x.id for x in gene_list_1]
    if hasattr(gene_list_2, 'id'):
        gene_list_2 = [x.id for x in gene_list_2]
        
    return({'x': gene_list_1, 'y': gene_list_2, 'data': deletion_array})

