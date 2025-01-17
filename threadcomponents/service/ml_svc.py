# NOTICE: As required by the Apache License v2.0, this notice is to state this file has been modified by Arachne Digital
# This file has been moved into a different directory
# To see its full history, please use `git log --follow <filename>` to view previous commits and additional contributors

import asyncio
import logging
import nltk
import os
import pandas as pd
import pickle
import random

from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split


class MLService:

    # Service to perform the machine learning against the pickle file
    def __init__(self, web_svc, dao, dir_prefix=''):
        self.web_svc = web_svc
        self.dao = dao
        self.dir_prefix = dir_prefix
        # Specify the location of the models file
        self.dict_loc = os.path.join(self.dir_prefix, 'threadcomponents', 'models', 'model_dict.p')

    async def build_models(self, tech_id, tech_name, techniques):
        """Function to build Logistic Regression Classification models based off of the examples provided."""
        lst1, lst2, false_list, sampling = [], [], [], []
        len_truelabels = 0

        for k, v in techniques.items():
            if v['id'] == tech_id:
                for i in v['example_uses']:
                    lst1.append(await self.web_svc.tokenize(i))
                    lst2.append(True)
                    len_truelabels += 1
                # Collect the false_positive samples here too, which are the incorrectly labeled texts from
                # reviewed reports, we will include these in the Negative Class.
                if 'false_positives' in v.keys():
                    for fp in v['false_positives']:
                        sampling.append(fp)
            else:
                for i in v['example_uses']:
                    false_list.append(await self.web_svc.tokenize(i))

        # At least 90% of total labels for both classes
        # use this for determining how many labels to use for classifier's negative class
        kval = int((len_truelabels * 10))

        # Add true/positive labels for OTHER techniques (false for given tech_id), use list obtained from above
        # Need if-checks because an empty list will cause an error with random.choices()
        if false_list:
            sampling.extend(random.choices(false_list, k=kval))

        # Finally, create the Negative Class for this technique's classification model
        # and include False as the labels for this training data
        for false_label in sampling:
            lst1.append(await self.web_svc.tokenize(false_label))
            lst2.append(False)

        # Convert into a dataframe
        df = pd.DataFrame({'text': lst1, 'category': lst2})

        # Build model based on that technique
        cv = CountVectorizer(max_features=2000)
        X = cv.fit_transform(df['text']).toarray()
        y = df['category']
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
        logreg = LogisticRegression(max_iter=2500, solver='lbfgs')
        logreg.fit(X_train, y_train)

        logging.info('{}, {} - {}'.format(tech_id, tech_name, logreg.score(X_test, y_test)))
        return (cv, logreg)

    async def analyze_document(self, cv, logreg, sentences):
        cleaned_sentences = [await self.web_svc.tokenize(i['text']) for i in sentences]

        df2 = pd.DataFrame({'text': cleaned_sentences})
        Xnew = cv.transform(df2['text']).toarray()
        await asyncio.sleep(0.01)
        y_pred = logreg.predict(Xnew)
        df2['category'] = y_pred.tolist()
        return df2

    async def build_pickle_file(self, list_of_techs, techniques, force=False):
        """Returns the classification models for the data provided."""
        # Have the models been rebuilt on calling this method?
        rebuilt = False
        # If we are not forcing the models to be rebuilt, obtain the previously used models
        if not force:
            model_dict = self.get_pre_saved_models()
            # If the models were obtained successfully, return them
            if model_dict:
                return rebuilt, model_dict
        # Else proceed with building the models
        model_dict = {}
        total = len(list_of_techs)
        count = 1
        logging.info('Building Classification Models.. This could take anywhere from ~30-60+ minutes. '
                     'Please do not close terminal.')
        for tech_id, tech_name in list_of_techs:
            logging.info('[#] Building.... {}/{}'.format(count, total))
            count += 1
            model_dict[tech_id] = await self.build_models(tech_id, tech_name, techniques)
        rebuilt = True
        logging.info('[#] Saving models to pickled file: ' + os.path.basename(self.dict_loc))
        # Save the newly-built models
        with open(self.dict_loc, 'wb') as saved_dict:
            pickle.dump(model_dict, saved_dict)
        logging.info('[#] Finished saving models.')
        return rebuilt, model_dict

    async def update_pickle_file(self, new_techs, list_of_techs, techniques):
        """Updates the current classification models with the new attacks."""
        # We are adding attacks and names are only used for logging: here, we don't have the names so use a desc string
        attack_name = 'New attack added'
        rebuilt, current_dict = await self.build_pickle_file(list_of_techs, techniques)
        if rebuilt:
            return  # models and pickle file include new attacks
        # If we retrieved the current models and they were not rebuilt, add the new attack-models to the pickle file
        for tech in new_techs:
            current_dict[tech] = await self.build_models(tech, attack_name, techniques)
        with open(self.dict_loc, 'wb') as saved_dict:
            pickle.dump(current_dict, saved_dict)

    def get_pre_saved_models(self, dictionary_location=None):
        """Function to retrieve previously-saved models via pickle."""
        if not dictionary_location:
            dictionary_location = self.dict_loc
        # Check the given location is a valid filepath
        if os.path.isfile(dictionary_location):
            logging.info('[#] Loading models from pickled file: ' + os.path.basename(dictionary_location))
            # Open the model file
            with open(dictionary_location, 'rb') as pre_saved_dict:
                # Attempt to load the model file's contents
                try:
                    # A UserWarning can appear stating the risks of using a different pickle version from sklearn
                    loaded = pickle.load(pre_saved_dict)
                    logging.info('[#] Successfully loaded models from pickled file')
                    return loaded
                # sklearn.linear_model.logistic has been required in a previous run; might be related to UserWarning
                except ModuleNotFoundError as mnfe:
                    logging.warning('Could not load existing models: ' + str(mnfe))
                # An empty file has been passed to pickle.load()
                except EOFError as eofe:
                    logging.warning('Existing models file may be empty: ' + str(eofe))
        # The provided location was not a valid filepath
        else:
            logging.warning('Invalid location given for existing models file.')
        # return None if pickle.load() was not successful or a valid filepath was not provided
        return None

    async def analyze_html(self, list_of_techs, model_dict, list_of_sentences):
        for tech_id, tech_name in list_of_techs:
            # If this loop takes long, the below logging-statement will help track progress
            # logging.info('%s/%s tech analysed' % (list_of_techs.index((tech_id, tech_name)), len(list_of_techs)))
            # If an older model_dict has been loaded, its keys may be out of sync with list_of_techs
            try:
                cv, logreg = model_dict[tech_id]
            except KeyError:  # Report to user if a model can't be retrieved
                logging.warning('Technique `' + tech_id + ', ' + tech_name + '` has no model to analyse with. '
                                + 'You can try deleting/moving models/model_dict.p to trigger re-build of models.')
                # Skip this technique and move onto the next one
                continue
            final_df = await self.analyze_document(cv, logreg, list_of_sentences)
            count = 0
            for vals in final_df['category']:
                await asyncio.sleep(0.001)
                if vals:
                    list_of_sentences[count]['ml_techniques_found'].append((tech_id, tech_name))
                count += 1
        return list_of_sentences

    async def ml_techniques_found(self, report_id, sentence, sentence_index, tech_start_date=None):
        sentence_id = await self.dao.insert_with_backup(
            'report_sentences', dict(report_uid=report_id, text=sentence['text'], html=sentence['html'],
                                     sen_index=sentence_index, found_status=self.dao.db_true_val))
        for technique_tid, technique_name in sentence['ml_techniques_found']:
            attack_uid = await self.dao.get('attack_uids', dict(tid=technique_tid))
            # If the attack cannot be found via the 'tid' column, try the 'name' column
            if not attack_uid:
                attack_uid = await self.dao.get('attack_uids', dict(name=technique_name))
            # If the attack has still not been retrieved, try searching the similar_words table
            if not attack_uid:
                similar_word = await self.dao.get('similar_words', dict(similar_word=technique_name))
                # If a similar word was found, use its attack_uid to lookup the attack_uids table
                if similar_word and similar_word[0] and similar_word[0]['attack_uid']:
                    attack_uid = await self.dao.get('attack_uids', dict(uid=similar_word[0]['attack_uid']))
            # If the attack has still not been retrieved, report to user that this cannot be saved against the sentence
            if not attack_uid:
                logging.warning(' '.join(('Sentence ID:', str(sentence_id), 'ML Technique:', technique_tid,
                                          technique_name, '- Technique could not be retrieved from the database; '
                                          + 'cannot save this technique\'s association with the sentence.')))
                # Skip this technique and continue with the next one
                continue
            attack_technique = attack_uid[0]['uid']
            attack_tech_name = attack_uid[0]['name']
            attack_tid = attack_uid[0]['tid']
            # Allow 'inactive' attacks to be recorded: they will be filtered out when viewing/exporting a report
            data = dict(sentence_id=sentence_id, attack_uid=attack_technique, attack_technique_name=attack_tech_name,
                        report_uid=report_id, attack_tid=attack_tid, initial_model_match=self.dao.db_true_val)
            if tech_start_date:
                data.update(dict(start_date=tech_start_date))
            await self.dao.insert_with_backup('report_sentence_hits', data)

    async def combine_ml_reg(self, ml_analyzed_html, reg_analyzed_html):
        analyzed_html = []
        index = 0
        for sentence in ml_analyzed_html:
            sentence['reg_techniques_found'] = reg_analyzed_html[index]['reg_techniques_found']
            analyzed_html.append(sentence)
            index += 1
        return analyzed_html

    async def check_nltk_packs(self):
        try:
            nltk.data.find('tokenizers/punkt')
            logging.info('[*] Found punkt')
        except LookupError:
            logging.warning('Could not find the punkt pack, downloading now')
            nltk.download('punkt')
        try:
            nltk.data.find('corpora/stopwords')
            logging.info('[*] Found stopwords')
        except LookupError:
            logging.warning('Could not find the stopwords pack, downloading now')
            nltk.download('stopwords')
        self.web_svc.initialise_tokenizer()
